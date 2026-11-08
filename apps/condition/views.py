from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.assets.models import Equipment
from apps.core.mixins import AuditedFormMixin
from apps.core.models import Attachment, AuditLog
from apps.core.services import log_action
from apps.workforce.models import technician_for

from . import selectors, services
from .forms import (
    CommentForm,
    ParameterForm,
    PointForm,
    RuleForm,
    SessionHeaderForm,
    ThresholdForm,
)
from .models import (
    LEVEL_BADGES,
    Alert,
    MeasurementPoint,
    MeasurementSession,
    Parameter,
    Threshold,
    TriggerRule,
)


def _tenant_user(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied


def _errors(request, form):
    for errors in form.errors.values():
        messages.error(request, " ".join(errors))


# --- Vue d'ensemble --------------------------------------------------------------------------

class OverviewView(CapabilityRequiredMixin, TemplateView):
    required_capability = "condition.view"
    template_name = "condition/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["data"] = selectors.overview()
        context["equipment_list"] = selectors.monitored_equipment()
        context["recent_sessions"] = MeasurementSession.objects.select_related("equipment", "technician")[:8]
        return context


# --- Paramètres ------------------------------------------------------------------------------

class ParameterListView(CapabilityRequiredMixin, ListView):
    required_capability = "condition.view"
    template_name = "condition/parameter_list.html"
    context_object_name = "parameters"

    def get_queryset(self):
        return Parameter.objects.all()


class _ParameterForm(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "condition.manage"
    form_class = ParameterForm
    template_name = "assets/simple_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_title": self.page_title, "back_url_name": "condition:parameter_list"}

    def get_success_url(self):
        return reverse("condition:parameter_list")


class ParameterCreateView(_ParameterForm, CreateView):
    page_title = gettext_lazy("Nouveau paramètre de mesure")
    success_message = gettext_lazy("Paramètre « %(name)s » créé.")


class ParameterUpdateView(_ParameterForm, UpdateView):
    page_title = gettext_lazy("Modifier le paramètre")
    success_message = gettext_lazy("Paramètre « %(name)s » mis à jour.")

    def get_queryset(self):
        return Parameter.objects.all()


# --- Points de mesure -----------------------------------------------------------------------

class PointCreateView(AuditedFormMixin, CapabilityRequiredMixin, CreateView):
    required_capability = "condition.manage"
    form_class = PointForm
    template_name = "condition/point_form.html"
    success_message = gettext_lazy("Point « %(name)s » créé.")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.tenant_id:
            self.equipment = get_object_or_404(Equipment, pk=kwargs["equipment_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "equipment": self.equipment}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "equipment": self.equipment}

    def form_valid(self, form):
        form.instance.equipment = self.equipment
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.get_absolute_url()


class PointUpdateView(AuditedFormMixin, CapabilityRequiredMixin, UpdateView):
    required_capability = "condition.manage"
    form_class = PointForm
    template_name = "condition/point_form.html"
    success_message = gettext_lazy("Point « %(name)s » mis à jour.")

    def get_queryset(self):
        return MeasurementPoint.objects.select_related("equipment")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "equipment": self.object.equipment}

    def get_success_url(self):
        return self.object.get_absolute_url()


class PointDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "condition.view"
    template_name = "condition/point_detail.html"
    context_object_name = "point"

    def get_queryset(self):
        return MeasurementPoint.objects.select_related("equipment").prefetch_related("parameters")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        point = self.object
        blocks = []
        for parameter in point.parameters.all():
            thresholds = list(Threshold.objects.filter(point=point, parameter=parameter).order_by("-valid_from", "-pk"))
            last = point.measurements.filter(parameter=parameter).order_by("-measured_at", "-pk").first()
            blocks.append({
                "parameter": parameter,
                "current": thresholds[0] if thresholds else None,
                "history": thresholds[1:6],
                "last": last,
                "series": services.chart_series(point, parameter),
                "chart_id": f"series-{parameter.pk}",
                "form": ThresholdForm(prefix=f"p{parameter.pk}", initial=_threshold_initial(thresholds[0] if thresholds else None)),
            })
        context["blocks"] = blocks
        context["measurements"] = point.measurements.select_related("parameter", "session")[:40]
        context["alerts"] = point.alerts.select_related("parameter").order_by("-opened_at")[:10]
        context["can_manage"] = self.request.user.has_capability("condition.manage")
        return context


def _threshold_initial(threshold):
    if threshold is None:
        return {}
    fields = ["warning_high", "alarm_high", "critical_high", "warning_low", "alarm_low", "critical_low", "source", "reference"]
    return {name: getattr(threshold, name) for name in fields}


@login_required
@require_POST
def threshold_save(request, pk, parameter_pk):
    """Enregistre une nouvelle version des seuils (les versions précédentes restent pour l'historique)."""
    _tenant_user(request)
    require_capability(request.user, "condition.manage")
    point = get_object_or_404(MeasurementPoint, pk=pk)
    parameter = get_object_or_404(point.parameters.all(), pk=parameter_pk)
    form = ThresholdForm(request.POST, prefix=f"p{parameter.pk}", instance=Threshold(point=point, parameter=parameter))
    if form.is_valid():
        threshold = form.save(commit=False)
        threshold.created_by = request.user
        threshold.save()
        log_action(AuditLog.Action.CREATE, request=request, obj=threshold,
                   changes={_("Seuils"): ["", f"{parameter.code} : {services.threshold_label(threshold, 'warning')} / "
                                              f"{services.threshold_label(threshold, 'alarm')} / {services.threshold_label(threshold, 'critical')}"]})
        messages.success(request, _("Seuils de « %(p)s » enregistrés.") % {"p": parameter.name})
    else:
        _errors(request, form)
    return redirect(f"{point.get_absolute_url()}#param-{parameter.pk}")


@login_required
def point_photo(request, pk):
    _tenant_user(request)
    require_capability(request.user, "condition.view")
    point = get_object_or_404(MeasurementPoint, pk=pk)
    if not point.photo:
        raise Http404
    return FileResponse(point.photo.open("rb"))


# --- Tournées et prélèvements ---------------------------------------------------------------------

def _grid(equipment, kind):
    """Points actifs de l'équipement et leurs paramètres, filtrés selon le type de tournée."""
    categories = {"vibration": ["vibration"], "oil": ["oil"]}.get(kind)
    rows = []
    for point in equipment.measurement_points.filter(is_active=True).prefetch_related("parameters"):
        params = [p for p in point.parameters.all() if p.is_active and (categories is None or p.category in categories)]
        if params:
            rows.append({"point": point, "params": params})
    return rows


class SessionCreateView(CapabilityRequiredMixin, TemplateView):
    required_capability = "condition.record"
    template_name = "condition/session_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.tenant_id:
            self.equipment = get_object_or_404(Equipment, pk=kwargs["equipment_pk"])
            kind = request.GET.get("type") or request.POST.get("kind") or "inspection"
            self.kind = kind if kind in MeasurementSession.Kind.values else "inspection"
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, form=None, values=None, **kwargs):
        context = super().get_context_data(**kwargs)
        grid = _grid(self.equipment, self.kind)
        values = values or {}
        for row in grid:
            row["cells"] = [{"parameter": p, "name": f"v-{row['point'].pk}-{p.pk}", "value": values.get(f"v-{row['point'].pk}-{p.pk}", "")} for p in row["params"]]
        context.update({
            "equipment": self.equipment, "kind": self.kind, "grid": grid, "kinds": MeasurementSession.Kind.choices,
            "form": form or SessionHeaderForm(initial={"kind": self.kind}, technician=technician_for(self.request.user)),
        })
        return context

    def post(self, request, *args, **kwargs):
        form = SessionHeaderForm(request.POST, request.FILES)
        grid = _grid(self.equipment, self.kind)
        raw = {key: value for key, value in request.POST.items() if key.startswith("v-")}
        values, errors = [], []
        for row in grid:
            for parameter in row["params"]:
                try:
                    value = services.parse_value(raw.get(f"v-{row['point'].pk}-{parameter.pk}"))
                except ValidationError as error:
                    errors.append(f"{row['point'].code} · {parameter.name} : {' '.join(error.messages)}")
                    continue
                if value is not None:
                    values.append((row["point"], parameter, value))
        if not form.is_valid() or errors:
            for message in errors:
                messages.error(request, message)
            return self.render_to_response(self.get_context_data(form=form, values=raw))
        header = {k: v for k, v in form.cleaned_data.items() if k not in ("kind", "measured_at", "technician", "report")}
        try:
            with transaction.atomic():
                session = services.record_session(
                    equipment=self.equipment, kind=self.kind, measured_at=form.cleaned_data["measured_at"], values=values,
                    user=request.user, technician=form.cleaned_data["technician"], **header,
                )
                report = form.cleaned_data.get("report")
                if report:
                    from apps.assets.forms import AttachmentForm

                    attachment_form = AttachmentForm(data={"category": "report", "title": ""}, files={"file": report})
                    if not attachment_form.is_valid():
                        raise ValidationError(attachment_form.errors.get("file") or _("Fichier refusé."))
                    attachment = attachment_form.save(commit=False)
                    attachment.content_object = session
                    attachment.original_name, attachment.size, attachment.created_by = report.name[:255], report.size, request.user
                    attachment.save()
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
            return self.render_to_response(self.get_context_data(form=form, values=raw))
        alerts = session.measurements.exclude(level__in=["normal", "unknown"]).count()
        if alerts:
            messages.warning(request, _("Mesures enregistrées : %(n)s valeur(s) hors seuil, voir les alertes.") % {"n": alerts})
        else:
            messages.success(request, _("Mesures enregistrées."))
        return redirect(session.get_absolute_url())


class SessionListView(CapabilityRequiredMixin, ListView):
    required_capability = "condition.view"
    template_name = "condition/session_list.html"
    context_object_name = "sessions"
    paginate_by = 30

    def get_queryset(self):
        queryset = MeasurementSession.objects.select_related("equipment", "technician")
        kind = self.request.GET.get("type")
        if kind in MeasurementSession.Kind.values:
            queryset = queryset.filter(kind=kind)
        equipment = self.request.GET.get("equipement")
        if equipment and equipment.isdigit():
            queryset = queryset.filter(equipment_id=int(equipment))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["kinds"] = MeasurementSession.Kind.choices
        context["current_kind"] = self.request.GET.get("type", "")
        return context


class SessionDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "condition.view"
    template_name = "condition/session_detail.html"
    context_object_name = "session"

    def get_queryset(self):
        return MeasurementSession.objects.select_related("equipment", "technician")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["measurements"] = self.object.measurements.select_related("point", "parameter", "threshold").order_by("point__code", "parameter__name")
        context["attachments"] = Attachment.objects.filter(
            content_type=ContentType.objects.get_for_model(MeasurementSession), object_id=self.object.pk,
        )
        return context


@login_required
def session_attachment(request, pk):
    _tenant_user(request)
    require_capability(request.user, "condition.view")
    attachment = get_object_or_404(Attachment, pk=pk, content_type=ContentType.objects.get_for_model(MeasurementSession))
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)


# --- Alertes ------------------------------------------------------------------------------------

class AlertListView(CapabilityRequiredMixin, ListView):
    required_capability = "condition.view"
    template_name = "condition/alert_list.html"
    context_object_name = "alerts"
    paginate_by = 40

    def get_queryset(self):
        status = self.request.GET.get("statut", "actives")
        queryset = Alert.objects.select_related("point", "point__equipment", "parameter", "last_measurement", "work_order", "work_request")
        if status == "actives":
            return selectors.sort_alerts(queryset.exclude(status=Alert.Status.CLOSED))
        if status in Alert.Status.values:
            return queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_status"] = self.request.GET.get("statut", "actives")
        context["statuses"] = [("actives", _("Actives"))] + list(Alert.Status.choices) + [("toutes", _("Toutes"))]
        return context


class AlertDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "condition.view"
    template_name = "condition/alert_detail.html"
    context_object_name = "alert"

    def get_queryset(self):
        return Alert.objects.select_related(
            "point", "point__equipment", "parameter", "first_measurement", "last_measurement", "last_measurement__threshold",
            "acknowledged_by", "closed_by", "rule", "work_order", "work_request",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        alert = self.object
        context["series"] = services.chart_series(alert.point, alert.parameter)
        context["measurements"] = alert.point.measurements.filter(parameter=alert.parameter).order_by("-measured_at")[:12]
        context["badges"] = LEVEL_BADGES
        return context


@login_required
@require_POST
def alert_action(request, pk, action):
    _tenant_user(request)
    alert = get_object_or_404(Alert.objects.select_related("point", "point__equipment", "parameter", "last_measurement"), pk=pk)
    form = CommentForm(request.POST)
    comment = form.cleaned_data["comment"] if form.is_valid() else ""
    try:
        if action == "acquitter":
            require_capability(request.user, "condition.record")
            services.acknowledge(alert, user=request.user, comment=comment)
            messages.success(request, _("Alerte acquittée."))
        elif action == "clore":
            require_capability(request.user, "condition.manage")
            services.close(alert, user=request.user, comment=comment)
            messages.success(request, _("Alerte close."))
        elif action == "creer-ot":
            work_order = services.create_work_order_from_alert(alert, user=request.user)
            messages.success(request, _("OT %(n)s créé.") % {"n": work_order.number})
            return redirect(work_order.get_absolute_url())
        elif action == "creer-di":
            work_request = services.create_request_from_alert(alert, user=request.user)
            messages.success(request, _("Demande %(n)s créée.") % {"n": work_request.number})
        else:
            raise Http404
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    target = request.POST.get("next")
    if target and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(alert.get_absolute_url())


# --- Règles -----------------------------------------------------------------------------------------

class RuleListView(CapabilityRequiredMixin, ListView):
    required_capability = "condition.view"
    template_name = "condition/rule_list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return TriggerRule.objects.select_related("parameter", "equipment")


class _RuleForm(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "condition.manage"
    form_class = RuleForm
    template_name = "assets/simple_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_title": self.page_title, "back_url_name": "condition:rule_list"}

    def get_success_url(self):
        return reverse("condition:rule_list")


class RuleCreateView(_RuleForm, CreateView):
    page_title = gettext_lazy("Nouvelle règle de déclenchement")
    success_message = gettext_lazy("Règle « %(name)s » créée.")


class RuleUpdateView(_RuleForm, UpdateView):
    page_title = gettext_lazy("Modifier la règle")
    success_message = gettext_lazy("Règle « %(name)s » mise à jour.")

    def get_queryset(self):
        return TriggerRule.objects.all()


def equipment_tab_context(request, equipment):
    """Contexte de l'onglet « Mesures » de la fiche équipement (appelé par le module patrimoine)."""
    return {
        "condition_rows": selectors.point_states(equipment),
        "condition_alerts": selectors.sort_alerts(selectors.active_alerts().filter(point__equipment=equipment)),
        "condition_sessions": equipment.measurement_sessions.select_related("technician")[:8],
        "level_badges": LEVEL_BADGES,
    }

