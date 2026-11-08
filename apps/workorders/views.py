import mimetypes

from django.apps import apps as django_apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.core.mixins import AuditedFormMixin
from apps.core.models import Attachment, AuditLog
from apps.core.services import form_changes, log_action
from apps.workforce.models import Technician, technician_for

from . import selectors, services
from .forms import (
    ChecklistItemForm,
    ExpenseForm,
    FailureCodeForm,
    PartForm,
    PlanningForm,
    ReportForm,
    TimeEntryForm,
    WorkOrderCreateForm,
    WorkRequestForm,
)
from .models import (
    ChecklistItem,
    Expense,
    FailureCode,
    PartUsage,
    Priority,
    TimeEntry,
    WorkOrder,
    WorkRequest,
)

PHOTO_CATEGORIES = [
    (Attachment.Category.PHOTO_BEFORE, gettext_lazy("Photo avant intervention")),
    (Attachment.Category.PHOTO_AFTER, gettext_lazy("Photo après intervention")),
    (Attachment.Category.REPORT, gettext_lazy("Rapport")),
    (Attachment.Category.OTHER, gettext_lazy("Autre document")),
]


def _tenant_user(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied


def _back(request, work_order):
    """Retour à la page d'origine (fiche ou écran technicien), uniquement vers une adresse de l'application."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect(work_order.get_absolute_url())


def _run(request, action, *args, success="", **kwargs):
    """Exécute un service et convertit ses erreurs en messages lisibles."""
    try:
        result = action(*args, **kwargs)
        if success:
            messages.success(request, success)
        return result
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return None


# --- Demandes d'intervention ---------------------------------------------------------------

class RequestListView(CapabilityRequiredMixin, ListView):
    required_capability = "requests.create"
    template_name = "workorders/request_list.html"
    context_object_name = "requests_list"
    paginate_by = 30

    def get_queryset(self):
        queryset = WorkRequest.objects.select_related("equipment", "requested_by", "work_order")
        if not self.request.user.has_capability("requests.manage"):
            queryset = queryset.filter(requested_by=self.request.user)
        status = self.request.GET.get("statut", "new" if self.request.user.has_capability("requests.manage") else "")
        if status in WorkRequest.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        default = "new" if self.request.user.has_capability("requests.manage") else ""
        context["current_status"] = self.request.GET.get("statut", default)
        context["statuses"] = WorkRequest.Status.choices
        return context


class RequestCreateView(CapabilityRequiredMixin, FormView):
    required_capability = "requests.create"
    form_class = WorkRequestForm
    template_name = "workorders/request_form.html"

    def get_initial(self):
        initial = super().get_initial()
        equipment = self.request.GET.get("equipement")
        if equipment and equipment.isdigit():
            initial["equipment"] = int(equipment)
        return initial

    def form_valid(self, form):
        request_obj = services.create_request(user=self.request.user, **form.cleaned_data)
        messages.success(self.request, _("Demande %(n)s enregistrée. La maintenance est prévenue.") % {"n": request_obj.number})
        return redirect(request_obj.get_absolute_url())


class RequestDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "requests.create"
    template_name = "workorders/request_detail.html"
    context_object_name = "request_obj"

    def get_queryset(self):
        queryset = WorkRequest.objects.select_related("equipment", "requested_by", "decided_by", "work_order")
        if not self.request.user.has_capability("requests.manage"):
            queryset = queryset.filter(requested_by=self.request.user)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["kinds"] = WorkOrder.Kind.choices
        context["priorities"] = Priority.choices
        return context


@login_required
@require_POST
def request_decide(request, pk, decision):
    _tenant_user(request)
    require_capability(request.user, "requests.manage")
    request_obj = get_object_or_404(WorkRequest, pk=pk)
    if decision == "accepter":
        priority = request.POST.get("priority")
        kind = request.POST.get("kind") if request.POST.get("kind") in WorkOrder.Kind.values else WorkOrder.Kind.CORRECTIVE
        work_order = _run(
            request, services.accept_request, request_obj, user=request.user, kind=kind,
            priority=int(priority) if priority and priority.isdigit() else None, note=request.POST.get("note", ""),
        )
        if work_order is not None:
            messages.success(request, _("Demande acceptée : %(n)s créé. Planifiez-le maintenant.") % {"n": work_order.number})
            return redirect("workorders:wo_plan", pk=work_order.pk)
    elif decision == "refuser":
        if _run(request, services.reject_request, request_obj, user=request.user, note=request.POST.get("note", "")):
            messages.success(request, _("Demande %(n)s refusée.") % {"n": request_obj.number})
    return redirect(request_obj.get_absolute_url())


# --- Ordres de travail : liste, création, planification --------------------------------------

class WorkOrderListView(CapabilityRequiredMixin, ListView):
    required_capability = "workorders.view"
    template_name = "workorders/wo_list.html"
    context_object_name = "work_orders"
    paginate_by = 30

    def get_queryset(self):
        return selectors.filter_work_orders(self.request.GET)

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and self.request.headers.get("HX-Target") == "wo-results":
            return ["workorders/_wo_results.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        counts = selectors.status_filter_counts(self.request.GET)
        context.update({
            "pills": [(key, label, counts[key]) for key, (label, _cond) in selectors.STATUS_FILTERS.items()],
            "current_status": self.request.GET.get("statut") or "ouverts",
            "kinds": WorkOrder.Kind.choices,
            "filters": self.request.GET,
            "filter_query": params.urlencode(),
            "new_requests": WorkRequest.objects.filter(status=WorkRequest.Status.NEW).count()
            if self.request.user.has_capability("requests.manage") else 0,
        })
        return context


class WorkOrderCreateView(CapabilityRequiredMixin, FormView):
    template_name = "workorders/wo_create.html"
    form_class = WorkOrderCreateForm

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not (user.has_capability("workorders.manage") or user.has_capability("workorders.create_direct")):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "simple": not self.request.user.has_capability("workorders.manage")}

    def get_initial(self):
        initial = super().get_initial()
        equipment = self.request.GET.get("equipement")
        if equipment and equipment.isdigit():
            initial["equipment"] = int(equipment)
        return initial

    def form_valid(self, form):
        data = dict(form.cleaned_data)
        technicians = data.pop("technicians", [])
        work_order = services.create_work_order(
            user=self.request.user, kind=data.pop("kind", WorkOrder.Kind.CORRECTIVE), technicians=technicians, **data,
        )
        messages.success(self.request, _("Ordre de travail %(n)s créé.") % {"n": work_order.number})
        if self.request.user.has_capability("workorders.manage"):
            return redirect(work_order.get_absolute_url())
        return redirect("workorders:wo_execute", pk=work_order.pk)


class WorkOrderPlanView(CapabilityRequiredMixin, UpdateView):
    required_capability = "workorders.manage"
    form_class = PlanningForm
    template_name = "workorders/wo_plan.html"
    context_object_name = "wo"

    def get_queryset(self):
        return WorkOrder.objects.select_related("equipment")

    def form_valid(self, form):
        try:
            services.plan_work_order(self.object, user=self.request.user, form=form)
        except ValidationError as error:
            messages.error(self.request, " ".join(error.messages))
            return redirect(self.object.get_absolute_url())
        messages.success(self.request, _("Planification de %(n)s enregistrée.") % {"n": self.object.number})
        return redirect(self.object.get_absolute_url())


# --- Ordres de travail : fiche et écran technicien ---------------------------------------------

def _work_order_context(request, work_order):
    user = request.user
    technician = technician_for(user)
    content_type = ContentType.objects.get_for_model(WorkOrder)
    can_execute = services._can_execute(user, work_order)
    editable = can_execute and (work_order.is_open or (work_order.status == WorkOrder.Status.DONE and user.has_capability("workorders.validate")))
    running = TimeEntry.objects.filter(work_order=work_order, technician=technician, ended_at__isnull=True).first() if technician else None
    context = {
        "wo": work_order,
        "technician": technician,
        "running_entry": running,
        "can_execute": can_execute,
        "can_manage": user.has_capability("workorders.manage"),
        "can_validate": user.has_capability("workorders.validate"),
        "editable": editable,
        "costs": services.compute_costs(work_order),
        "missing": services.finish_requirements(work_order) if work_order.is_open else [],
        "time_entries": work_order.time_entries.select_related("technician"),
        "parts": work_order.parts.all(),
        "expenses": work_order.expenses.all(),
        "checklist": work_order.checklist.all(),
        "status_logs": work_order.status_logs.select_related("user"),
        "attachments": Attachment.objects.filter(content_type=content_type, object_id=work_order.pk).select_related("created_by"),
        "downtimes": work_order.downtimes.all(),
        "report_form": ReportForm(instance=work_order),
        "part_form": PartForm(),
        "expense_form": ExpenseForm(),
        "checklist_form": ChecklistItemForm(),
        "time_form": TimeEntryForm(technicians=Technician.objects.filter(is_active=True)),
        "photo_categories": PHOTO_CATEGORIES,
        "plan_parts": list(work_order.preventive_plan.parts.all()) if work_order.preventive_plan_id else [],
    }
    # Pièces du magasin (module stock, en aval, s'il est installé).
    if django_apps.is_installed("apps.inventory") and user.has_capability("inventory.view"):
        from apps.inventory.views import work_order_context

        context.update(work_order_context(request, work_order))
        context["plan_parts"] = [part for part in context["plan_parts"] if not part.item_id]
    return context


class WorkOrderDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "workorders.view"
    template_name = "workorders/wo_detail.html"

    def get_queryset(self):
        return selectors.base_queryset().select_related("failure_mode", "failure_cause", "validated_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_work_order_context(self.request, self.object))
        return context


class WorkOrderExecuteView(WorkOrderDetailView):
    """Écran unique du technicien (pensé pour le téléphone), conforme à la maquette validée."""

    template_name = "workorders/wo_execute.html"


class MyWorkOrdersView(CapabilityRequiredMixin, TemplateView):
    required_capability = "workorders.view"
    template_name = "workorders/my_work_orders.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        technician = technician_for(self.request.user)
        context["technician"] = technician
        if technician is not None:
            mine = selectors.base_queryset().filter(technicians=technician)
            context["open_orders"] = mine.filter(status__in=WorkOrder.OPEN_STATUSES).order_by("priority", "due_date", "planned_date")
            context["recent_done"] = mine.filter(status__in=[WorkOrder.Status.DONE, WorkOrder.Status.VALIDATED]).order_by("-finished_at")[:10]
        return context


# --- Actions ---------------------------------------------------------------------------------

ACTION_MESSAGES = {
    "start_timer": gettext_lazy("Chronomètre démarré."),
    "stop_timer": gettext_lazy("Chronomètre arrêté."),
    "wait_parts": gettext_lazy("OT mis en attente de pièces."),
    "wait_external": gettext_lazy("OT mis en attente d'intervention externe."),
    "resume": gettext_lazy("Intervention reprise."),
    "finish": gettext_lazy("Intervention terminée. Elle attend maintenant la validation."),
    "validate": gettext_lazy("OT validé : les coûts sont figés."),
    "reopen": gettext_lazy("OT renvoyé au technicien."),
    "cancel": gettext_lazy("OT annulé."),
}


@login_required
@require_POST
def wo_action(request, pk, action):
    _tenant_user(request)
    work_order = get_object_or_404(WorkOrder, pk=pk)
    reason = request.POST.get("reason", "")
    handlers = {
        "start_timer": lambda: services.start_timer(work_order, user=request.user),
        "stop_timer": lambda: services.stop_timer(work_order, user=request.user),
        "wait_parts": lambda: services.put_on_hold(work_order, user=request.user, action="wait_parts", reason=reason),
        "wait_external": lambda: services.put_on_hold(work_order, user=request.user, action="wait_external", reason=reason),
        "resume": lambda: services.resume(work_order, user=request.user),
        "finish": lambda: services.finish(work_order, user=request.user),
        "validate": lambda: services.validate(work_order, user=request.user),
        "reopen": lambda: services.reopen(work_order, user=request.user, comment=reason),
        "cancel": lambda: services.cancel(work_order, user=request.user, reason=reason),
    }
    if action not in handlers:
        raise Http404
    _run(request, handlers[action], success=str(ACTION_MESSAGES[action]))
    return _back(request, work_order)


def _editable_work_order(request, pk):
    _tenant_user(request)
    work_order = get_object_or_404(WorkOrder, pk=pk)
    services.ensure_editable(work_order, request.user)
    return work_order


def _guarded(view):
    """Transforme les refus métier (OT clôturé...) en message, sans erreur 500."""

    def wrapper(request, pk, *args, **kwargs):
        try:
            return view(request, pk, *args, **kwargs)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            work_order = get_object_or_404(WorkOrder, pk=pk)
            return _back(request, work_order)

    wrapper.__name__ = view.__name__
    return login_required(require_POST(wrapper))


def _form_errors(request, form):
    for errors in form.errors.values():
        messages.error(request, " ".join(errors))


@_guarded
def wo_report(request, pk):
    work_order = _editable_work_order(request, pk)
    form = ReportForm(request.POST, instance=work_order)
    if form.is_valid():
        changes = form_changes(form)
        form.save()
        if changes:
            log_action(AuditLog.Action.UPDATE, request=request, obj=work_order, changes=changes)
        messages.success(request, _("Compte rendu enregistré."))
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@_guarded
def wo_part_add(request, pk):
    work_order = _editable_work_order(request, pk)
    form = PartForm(request.POST)
    if form.is_valid():
        part = form.save(commit=False)
        part.work_order, part.created_by = work_order, request.user
        part.save()
        messages.success(request, _("Pièce ajoutée."))
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@_guarded
def wo_part_delete(request, pk, item_pk):
    work_order = _editable_work_order(request, pk)
    get_object_or_404(PartUsage, pk=item_pk, work_order=work_order).delete()
    messages.success(request, _("Pièce retirée."))
    return _back(request, work_order)


@_guarded
def wo_expense_add(request, pk):
    work_order = _editable_work_order(request, pk)
    require_capability(request.user, "workorders.manage")
    form = ExpenseForm(request.POST)
    if form.is_valid():
        expense = form.save(commit=False)
        expense.work_order, expense.created_by = work_order, request.user
        expense.save()
        messages.success(request, _("Dépense ajoutée."))
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@_guarded
def wo_expense_delete(request, pk, item_pk):
    work_order = _editable_work_order(request, pk)
    require_capability(request.user, "workorders.manage")
    get_object_or_404(Expense, pk=item_pk, work_order=work_order).delete()
    messages.success(request, _("Dépense retirée."))
    return _back(request, work_order)


@_guarded
def wo_checklist_add(request, pk):
    work_order = _editable_work_order(request, pk)
    require_capability(request.user, "workorders.manage")
    form = ChecklistItemForm(request.POST)
    if form.is_valid():
        ChecklistItem.objects.create(
            work_order=work_order, label=form.cleaned_data["label"], position=work_order.checklist.count() + 1, created_by=request.user,
        )
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@_guarded
def wo_checklist_toggle(request, pk, item_pk):
    work_order = _editable_work_order(request, pk)
    item = get_object_or_404(ChecklistItem, pk=item_pk, work_order=work_order)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done", "updated_at"])
    if request.headers.get("HX-Request"):
        return render(request, "workorders/_checklist_item.html", {"item": item, "wo": work_order, "editable": True})
    return _back(request, work_order)


@_guarded
def wo_time_add(request, pk):
    work_order = _editable_work_order(request, pk)
    form = TimeEntryForm(request.POST, technicians=Technician.objects.filter(is_active=True))
    if form.is_valid():
        data = form.cleaned_data
        _run(
            request, services.add_time_entry, work_order, user=request.user, technician=data["technician"],
            started_at=data["started_at"], ended_at=data["ended_at"], is_overtime=data["is_overtime"], note=data["note"],
            success=_("Temps ajouté."),
        )
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@_guarded
def wo_time_delete(request, pk, item_pk):
    work_order = _editable_work_order(request, pk)
    require_capability(request.user, "workorders.manage")
    entry = get_object_or_404(TimeEntry, pk=item_pk, work_order=work_order)
    log_action(AuditLog.Action.UPDATE, request=request, obj=work_order, changes={_("Pointage supprimé"): [f"{entry.technician} {entry.hours} h", ""]})
    entry.delete()
    messages.success(request, _("Pointage supprimé."))
    return _back(request, work_order)


@_guarded
def wo_attachment_upload(request, pk):
    from apps.assets.forms import AttachmentForm

    work_order = _editable_work_order(request, pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.content_object = work_order
        attachment.original_name = request.FILES["file"].name[:255]
        attachment.size = request.FILES["file"].size
        attachment.created_by = request.user
        attachment.save()
        messages.success(request, _("Fichier ajouté."))
    else:
        _form_errors(request, form)
    return _back(request, work_order)


@login_required
def wo_attachment_file(request, pk):
    """Photos et documents d'un OT, servis après contrôle de l'entreprise et des droits."""
    _tenant_user(request)
    require_capability(request.user, "workorders.view")
    attachment = get_object_or_404(Attachment, pk=pk, content_type=ContentType.objects.get_for_model(WorkOrder))
    content_type = mimetypes.guess_type(attachment.original_name)[0] or "application/octet-stream"
    inline = content_type.startswith("image/") and request.GET.get("telecharger") != "1"
    return FileResponse(attachment.file.open("rb"), as_attachment=not inline, filename=attachment.original_name, content_type=content_type)


# --- Codes de défaillance ------------------------------------------------------------------------

class FailureCodeListView(CapabilityRequiredMixin, ListView):
    required_capability = "workorders.manage"
    template_name = "workorders/failure_codes.html"
    context_object_name = "codes"

    def get_queryset(self):
        return FailureCode.objects.all()


class _FailureCodeForm(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "workorders.manage"
    form_class = FailureCodeForm
    template_name = "assets/simple_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_title": self.page_title, "back_url_name": "workorders:failure_codes"}

    def get_success_url(self):
        return reverse("workorders:failure_codes")


class FailureCodeCreateView(_FailureCodeForm, CreateView):
    page_title = gettext_lazy("Nouveau code de défaillance")
    success_message = gettext_lazy("Code « %(name)s » créé.")


class FailureCodeUpdateView(_FailureCodeForm, UpdateView):
    page_title = gettext_lazy("Modifier le code de défaillance")
    success_message = gettext_lazy("Code « %(name)s » mis à jour.")

    def get_queryset(self):
        return FailureCode.objects.all()


@login_required
def wo_pdf(request, pk):
    """Fiche d'intervention PDF : vierge avant les travaux, compte rendu après."""
    require_capability(request.user, "workorders.view")
    from .documents import work_order_pdf

    wo = get_object_or_404(WorkOrder.objects.select_related("equipment__location", "team", "contractor", "preventive_plan",
                                                            "failure_mode", "failure_cause", "validated_by"), pk=pk)
    content = work_order_pdf(wo, tenant=request.tenant, user=request.user)
    log_action(AuditLog.Action.EXPORT, request=request, obj=wo, changes={"Export": ["", "Fiche d'intervention (PDF)"]})
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{wo.number}.pdf"'
    return response


@login_required
def wo_export(request):
    """Export Excel de la liste des OT, avec les filtres de l'écran."""
    require_capability(request.user, "workorders.view")
    from .documents import work_orders_xlsx

    queryset = selectors.filter_work_orders(request.GET).order_by("-created_at")[:20000]
    content = work_orders_xlsx(queryset)
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Liste des OT (Excel)"]})
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="interventions-{timezone.localdate():%Y%m%d}.xlsx"'
    return response
