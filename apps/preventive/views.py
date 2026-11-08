import calendar
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.core.formatting import month_name, weekday_abbreviations
from apps.core.models import Attachment, AuditLog
from apps.core.services import form_changes, log_action
from apps.workforce.models import Team, Technician
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder

from . import selectors, services
from .forms import PlanPartForm, PostponeForm, PreventivePlanForm
from .models import PlanChecklistItem, PlanPart, PreventivePlan


def _tenant_user(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied


# --- Plans ----------------------------------------------------------------------------

class PlanListView(CapabilityRequiredMixin, TemplateView):
    required_capability = "preventive.view"
    template_name = "preventive/plan_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["rows"] = selectors.plans_with_status(self.request.GET)
        context["filters"] = self.request.GET
        context["compliance"] = selectors.compliance()
        return context


class _PlanFormMixin(CapabilityRequiredMixin):
    required_capability = "preventive.manage"
    form_class = PreventivePlanForm
    template_name = "preventive/plan_form.html"

    @transaction.atomic
    def form_valid(self, form):
        is_new = form.instance.pk is None
        changes = {} if is_new else form_changes(form)
        if is_new:
            form.instance.created_by = self.request.user
        self.object = form.save()
        lines = form.checklist_lines()
        current = list(self.object.checklist.values_list("label", flat=True))
        if lines != current:
            self.object.checklist.all().delete()
            for position, label in enumerate(lines, start=1):
                PlanChecklistItem.objects.create(plan=self.object, label=label, position=position, created_by=self.request.user)
            if not is_new:
                changes[str(_("Check-list"))] = [f"{len(current)} point(s)", f"{len(lines)} point(s)"]
        if is_new:
            log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
            messages.success(self.request, _("Plan %(code)s créé.") % {"code": self.object.code})
        else:
            if changes:
                log_action(AuditLog.Action.UPDATE, request=self.request, obj=self.object, changes=changes)
            messages.success(self.request, _("Plan %(code)s mis à jour.") % {"code": self.object.code})
        return redirect(self.object.get_absolute_url())


class PlanCreateView(_PlanFormMixin, CreateView):
    def get_initial(self):
        initial = super().get_initial()
        equipment = self.request.GET.get("equipement")
        if equipment and equipment.isdigit():
            initial["equipment"] = int(equipment)
        initial["next_due_date"] = timezone.localdate() + timedelta(days=7)
        initial["period_value"] = 1
        return initial


class PlanUpdateView(_PlanFormMixin, UpdateView):
    def get_queryset(self):
        return PreventivePlan.objects.all()


class PlanDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "preventive.view"
    template_name = "preventive/plan_detail.html"
    context_object_name = "plan"

    def get_queryset(self):
        return PreventivePlan.objects.select_related("equipment", "meter", "team")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan = self.object
        today = timezone.localdate()
        due, due_date, reason = services.due_status(plan, today)
        content_type = ContentType.objects.get_for_model(PreventivePlan)
        context.update({
            "pending": services.pending_work_order(plan),
            "is_due": due, "due_date": due_date, "due_reason": reason,
            "meter_estimate": services.estimated_meter_date(plan, today) if plan.uses_meter else None,
            "history": plan.work_orders.select_related("equipment").order_by("-created_at")[:30],
            "part_form": PlanPartForm(),
            "attachments": Attachment.objects.filter(content_type=content_type, object_id=plan.pk),
            "can_manage": self.request.user.has_capability("preventive.manage"),
        })
        return context


@login_required
@require_POST
def plan_generate(request, pk):
    _tenant_user(request)
    plan = get_object_or_404(PreventivePlan, pk=pk)
    try:
        work_order = services.generate_now(plan, user=request.user)
        messages.success(request, _("OT %(n)s créé à partir du plan.") % {"n": work_order.number})
        return redirect(work_order.get_absolute_url())
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect(plan.get_absolute_url())


@login_required
@require_POST
def plan_part_add(request, pk):
    _tenant_user(request)
    require_capability(request.user, "preventive.manage")
    plan = get_object_or_404(PreventivePlan, pk=pk)
    form = PlanPartForm(request.POST)
    if form.is_valid():
        part = form.save(commit=False)
        part.plan, part.created_by = plan, request.user
        part.save()
        messages.success(request, _("Pièce ajoutée au plan."))
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect(plan.get_absolute_url())


@login_required
@require_POST
def plan_part_delete(request, pk, item_pk):
    _tenant_user(request)
    require_capability(request.user, "preventive.manage")
    plan = get_object_or_404(PreventivePlan, pk=pk)
    get_object_or_404(PlanPart, pk=item_pk, plan=plan).delete()
    messages.success(request, _("Pièce retirée du plan."))
    return redirect(plan.get_absolute_url())


@login_required
@require_POST
def plan_attachment_upload(request, pk):
    from apps.assets.forms import AttachmentForm

    _tenant_user(request)
    require_capability(request.user, "preventive.manage")
    plan = get_object_or_404(PreventivePlan, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.content_object = plan
        attachment.original_name = request.FILES["file"].name[:255]
        attachment.size = request.FILES["file"].size
        attachment.created_by = request.user
        attachment.save()
        messages.success(request, _("Document ajouté au plan."))
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect(plan.get_absolute_url())


@login_required
def plan_attachment_file(request, pk):
    _tenant_user(request)
    require_capability(request.user, "preventive.view")
    attachment = get_object_or_404(Attachment, pk=pk, content_type=ContentType.objects.get_for_model(PreventivePlan))
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)


# --- Report d'un OT -----------------------------------------------------------------------

@login_required
@require_POST
def work_order_postpone(request, pk):
    _tenant_user(request)
    work_order = get_object_or_404(WorkOrder, pk=pk)
    form = PostponeForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
        return redirect(work_order.get_absolute_url())
    try:
        wo_services.postpone(work_order, user=request.user, new_date=form.cleaned_data["new_date"], reason=form.cleaned_data["reason"])
        messages.success(request, _("OT reporté au %(d)s.") % {"d": form.cleaned_data["new_date"].strftime("%d/%m/%Y")})
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect(work_order.get_absolute_url())


# --- Planning ---------------------------------------------------------------------------------

def _parse_day(value, default):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


class PlanningView(CapabilityRequiredMixin, TemplateView):
    """Planning des interventions : vues jour, semaine, mois. Les prévisions des plans apparaissent en pointillé."""

    required_capability = "workorders.view"
    template_name = "preventive/planning.html"
    VIEWS = [("jour", gettext_lazy("Jour")), ("semaine", gettext_lazy("Semaine")), ("mois", gettext_lazy("Mois"))]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        mode = self.request.GET.get("vue", "semaine")
        if mode not in dict(self.VIEWS):
            mode = "semaine"
        current = _parse_day(self.request.GET.get("date"), today)
        team = self.request.GET.get("equipe")
        team = int(team) if team and team.isdigit() else None
        technician = self.request.GET.get("technicien")
        technician = int(technician) if technician and technician.isdigit() else None

        if mode == "jour":
            start = end = current
            previous, following = current - timedelta(days=1), current + timedelta(days=1)
            title = f"{weekday_abbreviations()[current.weekday()]} {current:%d/%m/%Y}"
        elif mode == "semaine":
            start = current - timedelta(days=current.weekday())
            end = start + timedelta(days=6)
            previous, following = start - timedelta(days=7), start + timedelta(days=7)
            title = _("Semaine du %(a)s au %(b)s") % {"a": f"{start:%d/%m}", "b": f"{end:%d/%m/%Y}"}
        else:
            first = current.replace(day=1)
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            start = first - timedelta(days=first.weekday())
            end = last + timedelta(days=6 - last.weekday())
            previous = (first - timedelta(days=1)).replace(day=1)
            following = last + timedelta(days=1)
            title = f"{month_name(first.month).capitalize()} {first.year}"

        items = selectors.planning_items(start, end, team=team, technician=technician)
        by_day = {}
        for item in items:
            by_day.setdefault(item["day"], []).append(item)
        days = []
        cursor = start
        while cursor <= end:
            days.append({
                "date": cursor, "label": weekday_abbreviations()[cursor.weekday()], "items": by_day.get(cursor, []),
                "is_today": cursor == today, "outside": mode == "mois" and cursor.month != current.month,
                "estimated_hours": sum((i["wo"].estimated_hours or 0) for i in by_day.get(cursor, []) if i["kind"] == "order"),
            })
            cursor += timedelta(days=1)
        weeks = [days[i:i + 7] for i in range(0, len(days), 7)]
        params = self.request.GET.copy()
        for key in ("date", "vue"):
            params.pop(key, None)
        context.update({
            "mode": mode, "views": self.VIEWS, "title": title, "days": days, "weeks": weeks, "weekdays": weekday_abbreviations(),
            "current": current, "previous": previous, "following": following, "today": today,
            "teams": Team.objects.filter(is_active=True), "technicians": Technician.objects.filter(is_active=True),
            "team": team, "technician": technician, "extra": params.urlencode(),
            "count": sum(1 for i in items if i["kind"] == "order"), "forecast_count": sum(1 for i in items if i["kind"] == "forecast"),
        })
        return context
