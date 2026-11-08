import io
import mimetypes

from django.apps import apps as django_apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.core.mixins import AuditedFormMixin
from apps.core.models import Attachment, AuditLog
from apps.core.services import form_changes, log_action

from . import selectors
from .forms import (
    AttachmentForm,
    EquipmentFamilyForm,
    EquipmentForm,
    LocationForm,
    ManufacturerForm,
    MeterForm,
    ReadingForm,
)
from .models import (
    Equipment,
    EquipmentFamily,
    Location,
    Manufacturer,
    Meter,
    MeterReading,
)
from .services import change_status, record_reading


def _tenant_required(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied


# --- Équipements ----------------------------------------------------------------

class EquipmentListView(CapabilityRequiredMixin, ListView):
    required_capability = "assets.view"
    template_name = "assets/equipment_list.html"
    context_object_name = "equipment_list"
    paginate_by = 25

    def get_queryset(self):
        return selectors.filter_equipment(self.request.GET)

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and self.request.headers.get("HX-Target") == "equipment-results":
            return ["assets/_equipment_results.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context.update({
            "paths": selectors.location_paths(),
            "status_counts": selectors.status_counts(),
            "statuses": Equipment.Status.choices,
            "criticalities": Equipment.Criticality.choices,
            "families": EquipmentFamily.objects.filter(is_active=True).select_related("parent"),
            "location_choices": selectors.location_choices(),
            "filters": self.request.GET,
            "filter_query": params.urlencode(),
        })
        return context


class EquipmentExportView(CapabilityRequiredMixin, View):
    """Export Excel de la liste filtrée."""

    required_capability = "assets.view"

    def get(self, request):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        paths = selectors.location_paths()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = gettext("Équipements")
        headers = [
            gettext("Code"), gettext("Désignation"), gettext("Famille"), gettext("Localisation"), gettext("État"), gettext("Criticité"), gettext("Fabricant"), gettext("Marque"),
            gettext("Modèle"), gettext("N° de série"), gettext("Mise en service"), gettext("Équipement parent"),
        ]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for item in selectors.filter_equipment(request.GET).select_related("parent"):
            sheet.append([
                item.code, item.designation, str(item.family), paths.get(item.location_id, ""),
                item.get_status_display(), item.criticality, item.manufacturer.name if item.manufacturer else "",
                item.brand, item.model, item.serial_number, item.commissioning_date,
                item.parent.code if item.parent else "",
            ])
        for column, width in zip("ABCDEFGHIJKL", [16, 40, 28, 40, 12, 10, 20, 16, 18, 18, 14, 16], strict=True):
            sheet.column_dimensions[column].width = width
        for row in sheet.iter_rows(min_row=2, min_col=11, max_col=11):
            for cell in row:
                cell.number_format = "DD/MM/YYYY"
        buffer = io.BytesIO()
        workbook.save(buffer)
        log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Liste des équipements (Excel)"]})
        response = HttpResponse(
            buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="equipements-{timezone.localdate():%Y%m%d}.xlsx"'
        return response


class EquipmentDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "assets.view"
    template_name = "assets/equipment_detail.html"
    context_object_name = "equipment"
    TABS = [
        ("resume", gettext_lazy("Résumé")), ("interventions", gettext_lazy("Interventions")), ("mesures", gettext_lazy("Mesures")),
        ("pieces", gettext_lazy("Pièces")), ("couts", gettext_lazy("Coûts")), ("compteurs", gettext_lazy("Compteurs")),
        ("documents", gettext_lazy("Documents")), ("historique", gettext_lazy("Historique des modifications")),
    ]

    def get_queryset(self):
        return Equipment.objects.select_related("location", "family", "family__parent", "manufacturer", "parent", "responsible")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        equipment = self.object
        tab = self.request.GET.get("onglet", "resume")
        if tab not in dict(self.TABS):
            tab = "resume"
        content_type = ContentType.objects.get_for_model(Equipment)
        context.update({
            "tab": tab,
            "tabs": self.TABS,
            "location_path": equipment.location.full_path,
            "children": equipment.children.select_related("location").order_by("code"),
            "meters": equipment.meters.all(),
            "attachment_count": Attachment.objects.filter(content_type=content_type, object_id=equipment.pk).count(),
            "statuses": Equipment.Status.choices,
        })
        # Interventions : lues via le module workorders s'il est installé (dépendance optionnelle, vers l'aval).
        if django_apps.is_installed("apps.workorders") and self.request.user.has_capability("workorders.view"):
            from apps.workorders.selectors import equipment_history

            context["interventions"] = equipment_history(equipment)
        if django_apps.is_installed("apps.preventive") and self.request.user.has_capability("preventive.view"):
            context["plans"] = equipment.preventive_plans.filter(is_active=True).select_related("meter")
            context["show_plans"] = True
        if tab == "mesures" and django_apps.is_installed("apps.condition") and self.request.user.has_capability("condition.view"):
            from apps.condition.views import equipment_tab_context

            context.update(equipment_tab_context(self.request, equipment))
            context["show_condition"] = True
        if tab == "pieces" and django_apps.is_installed("apps.inventory") and self.request.user.has_capability("inventory.view"):
            from apps.inventory.views import equipment_tab_context as parts_tab_context

            context.update(parts_tab_context(self.request, equipment))
            context["show_parts"] = True
        if tab == "couts" and django_apps.is_installed("apps.finance") and self.request.user.has_capability("costs.view"):
            from apps.finance.views import equipment_tab_context as costs_tab_context

            context.update(costs_tab_context(self.request, equipment))
            context["show_costs"] = True
        if tab == "compteurs":
            context["reading_form"] = ReadingForm()
            context["recent_readings"] = (
                MeterReading.objects.filter(meter__equipment=equipment).select_related("meter", "created_by")[:30]
            )
        elif tab == "documents":
            context["attachments"] = Attachment.objects.filter(content_type=content_type, object_id=equipment.pk).select_related("created_by")
            context["attachment_form"] = AttachmentForm()
        elif tab == "historique":
            context["history"] = AuditLog.objects.filter(
                tenant=self.request.tenant, object_type=Equipment._meta.label, object_id=str(equipment.pk),
            ).select_related("user")[:100]
        return context


class EquipmentCreateView(CapabilityRequiredMixin, CreateView):
    required_capability = "assets.manage"
    form_class = EquipmentForm
    template_name = "assets/equipment_form.html"

    def get_initial(self):
        initial = super().get_initial()
        for param, field in (("localisation", "location"), ("parent", "parent")):
            value = self.request.GET.get(param)
            if value and value.isdigit():
                initial[field] = int(value)
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
        messages.success(self.request, _("Équipement %(code)s créé.") % {"code": self.object.code})
        return response


class EquipmentUpdateView(CapabilityRequiredMixin, UpdateView):
    required_capability = "assets.manage"
    form_class = EquipmentForm
    template_name = "assets/equipment_form.html"
    context_object_name = "equipment"

    def get_queryset(self):
        return Equipment.objects.all()

    def form_valid(self, form):
        changes = form_changes(form)
        response = super().form_valid(form)
        if changes:
            log_action(AuditLog.Action.UPDATE, request=self.request, obj=self.object, changes=changes)
        messages.success(self.request, _("Équipement %(code)s mis à jour.") % {"code": self.object.code})
        return response


@login_required
@require_POST
def equipment_change_status(request, pk):
    _tenant_required(request)
    require_capability(request.user, "assets.manage")
    equipment = get_object_or_404(Equipment, pk=pk)
    try:
        change_status(equipment, request.POST.get("status", ""), request=request)
        messages.success(request, _("État de %(code)s : %(status)s.") % {"code": equipment.code, "status": equipment.get_status_display()})
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect(equipment.get_absolute_url())


@login_required
def equipment_photo(request, pk):
    """Les photos ne sont jamais servies en accès public : contrôle d'accès à chaque lecture."""
    _tenant_required(request)
    require_capability(request.user, "assets.view")
    equipment = get_object_or_404(Equipment, pk=pk)
    if not equipment.photo:
        raise Http404
    content_type = mimetypes.guess_type(equipment.photo.name)[0] or "application/octet-stream"
    return FileResponse(equipment.photo.open("rb"), content_type=content_type)


# --- Compteurs -------------------------------------------------------------------

class MeterCreateView(CapabilityRequiredMixin, CreateView):
    required_capability = "assets.manage"
    form_class = MeterForm
    template_name = "assets/meter_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.tenant_id:
            self.equipment = get_object_or_404(Equipment, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "equipment": self.equipment}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "equipment": self.equipment}

    def form_valid(self, form):
        form.instance.equipment = self.equipment
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(AuditLog.Action.CREATE, request=self.request, obj=self.object)
        messages.success(self.request, _("Compteur « %(name)s » ajouté.") % {"name": self.object.name})
        return response

    def get_success_url(self):
        return f"{self.equipment.get_absolute_url()}?onglet=compteurs"


@login_required
@require_POST
def reading_create(request, meter_pk):
    _tenant_required(request)
    require_capability(request.user, "meters.record")
    meter = get_object_or_404(Meter.objects.select_related("equipment"), pk=meter_pk)
    form = ReadingForm(request.POST)
    target = f"{meter.equipment.get_absolute_url()}?onglet=compteurs"
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
        return redirect(target)
    try:
        record_reading(
            meter, form.cleaned_data["value"], reading_at=form.cleaned_data["reading_at"],
            user=request.user, note=form.cleaned_data["note"],
        )
        messages.success(request, _("Relevé enregistré pour « %(name)s ».") % {"name": meter.name})
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect(target)


# --- Pièces jointes ----------------------------------------------------------------

@login_required
@require_POST
def attachment_upload(request, pk):
    _tenant_required(request)
    require_capability(request.user, "assets.manage")
    equipment = get_object_or_404(Equipment, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.content_object = equipment
        attachment.original_name = request.FILES["file"].name[:255]
        attachment.size = request.FILES["file"].size
        attachment.created_by = request.user
        attachment.save()
        log_action(AuditLog.Action.UPDATE, request=request, obj=equipment, changes={_("Document ajouté"): ["", attachment.display_name]})
        messages.success(request, _("Document ajouté."))
    else:
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
    return redirect(f"{equipment.get_absolute_url()}?onglet=documents")


@login_required
def attachment_download(request, pk):
    _tenant_required(request)
    attachment = get_object_or_404(Attachment, pk=pk)
    if attachment.content_type.model_class() is Equipment:
        require_capability(request.user, "assets.view")
    else:
        raise Http404
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)


@login_required
@require_POST
def attachment_delete(request, pk):
    _tenant_required(request)
    require_capability(request.user, "assets.manage")
    attachment = get_object_or_404(Attachment, pk=pk, content_type=ContentType.objects.get_for_model(Equipment))
    equipment = get_object_or_404(Equipment, pk=attachment.object_id)
    name = attachment.display_name
    attachment.file.delete(save=False)
    attachment.delete()
    log_action(AuditLog.Action.UPDATE, request=request, obj=equipment, changes={_("Document supprimé"): [name, ""]})
    messages.success(request, _("Document supprimé."))
    return redirect(f"{equipment.get_absolute_url()}?onglet=documents")


# --- QR codes --------------------------------------------------------------------

def _qr_svg(url):
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()


@login_required
def equipment_qr(request, pk):
    _tenant_required(request)
    require_capability(request.user, "assets.view")
    equipment = get_object_or_404(Equipment, pk=pk)
    url = request.build_absolute_uri(reverse("assets:qr_resolve", args=[equipment.qr_token]))
    return HttpResponse(_qr_svg(url), content_type="image/svg+xml")


@login_required
def equipment_qr_labels(request):
    """Planche d'étiquettes imprimable (les équipements sélectionnés ou filtrés)."""
    _tenant_required(request)
    require_capability(request.user, "assets.view")
    ids = [int(value) for value in request.GET.getlist("id") if value.isdigit()]
    queryset = Equipment.objects.filter(pk__in=ids) if ids else selectors.filter_equipment(request.GET)
    paths = selectors.location_paths()
    labels = [{"equipment": item, "path": paths.get(item.location_id, "")} for item in queryset[:240]]
    return render(request, "assets/qr_labels.html", {"labels": labels})


@login_required
def qr_resolve(request, token):
    """Lien contenu dans le QR code : il ne révèle aucun identifiant interne."""
    _tenant_required(request)
    equipment = get_object_or_404(Equipment, qr_token=token)
    return redirect(equipment.get_absolute_url())


# --- Localisations ----------------------------------------------------------------

class LocationTreeView(CapabilityRequiredMixin, TemplateView):
    required_capability = "assets.view"
    template_name = "assets/location_tree.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "tree": selectors.location_tree()}


_AuditedFormMixin = AuditedFormMixin  # défini dans apps.core.mixins, partagé par les modules


class LocationCreateView(_AuditedFormMixin, CapabilityRequiredMixin, CreateView):
    required_capability = "assets.manage"
    form_class = LocationForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Localisation « %(name)s » créée.")
    extra_context = {"page_title": gettext_lazy("Nouvelle localisation"), "back_url_name": "assets:location_tree"}

    def get_initial(self):
        initial = super().get_initial()
        parent = self.request.GET.get("parent")
        if parent and parent.isdigit():
            initial["parent"] = int(parent)
            parent_location = Location.objects.filter(pk=int(parent)).first()
            if parent_location is not None:
                next_kind = {"site": "workshop", "workshop": "line", "line": "zone"}.get(parent_location.kind, "zone")
                initial["kind"] = next_kind
        return initial

    def get_success_url(self):
        return reverse("assets:location_tree")


class LocationUpdateView(_AuditedFormMixin, CapabilityRequiredMixin, UpdateView):
    required_capability = "assets.manage"
    form_class = LocationForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Localisation « %(name)s » mise à jour.")
    extra_context = {"page_title": gettext_lazy("Modifier la localisation"), "back_url_name": "assets:location_tree"}

    def get_queryset(self):
        return Location.objects.all()

    def get_success_url(self):
        return reverse("assets:location_tree")


# --- Familles et fabricants ---------------------------------------------------------

class ReferentialListView(CapabilityRequiredMixin, TemplateView):
    required_capability = "assets.manage"
    template_name = "assets/referentials.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["families"] = EquipmentFamily.objects.select_related("parent").annotate(n=Count("equipment")).order_by("parent__name", "name")
        context["manufacturers"] = Manufacturer.objects.annotate(n=Count("equipment"))
        return context


class FamilyCreateView(_AuditedFormMixin, CapabilityRequiredMixin, CreateView):
    required_capability = "assets.manage"
    form_class = EquipmentFamilyForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Famille « %(name)s » créée.")
    extra_context = {"page_title": gettext_lazy("Nouvelle famille d'équipements"), "back_url_name": "assets:family_list"}

    def get_success_url(self):
        return reverse("assets:family_list")


class FamilyUpdateView(_AuditedFormMixin, CapabilityRequiredMixin, UpdateView):
    required_capability = "assets.manage"
    form_class = EquipmentFamilyForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Famille « %(name)s » mise à jour.")
    extra_context = {"page_title": gettext_lazy("Modifier la famille"), "back_url_name": "assets:family_list"}

    def get_queryset(self):
        return EquipmentFamily.objects.all()

    def get_success_url(self):
        return reverse("assets:family_list")


class ManufacturerCreateView(_AuditedFormMixin, CapabilityRequiredMixin, CreateView):
    required_capability = "assets.manage"
    form_class = ManufacturerForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Fabricant « %(name)s » créé.")
    extra_context = {"page_title": gettext_lazy("Nouveau fabricant"), "back_url_name": "assets:family_list"}

    def get_success_url(self):
        return reverse("assets:family_list")


class ManufacturerUpdateView(_AuditedFormMixin, CapabilityRequiredMixin, UpdateView):
    required_capability = "assets.manage"
    form_class = ManufacturerForm
    template_name = "assets/simple_form.html"
    success_message = gettext_lazy("Fabricant « %(name)s » mis à jour.")
    extra_context = {"page_title": gettext_lazy("Modifier le fabricant"), "back_url_name": "assets:family_list"}

    def get_queryset(self):
        return Manufacturer.objects.all()

    def get_success_url(self):
        return reverse("assets:family_list")


@login_required
def equipment_pdf(request, pk):
    """Fiche équipement PDF."""
    require_capability(request.user, "assets.view")
    from .documents import equipment_pdf as build

    equipment = get_object_or_404(Equipment.objects.select_related("family", "location", "manufacturer", "responsible", "parent"), pk=pk)
    content = build(equipment, tenant=request.tenant, user=request.user)
    log_action(AuditLog.Action.EXPORT, request=request, obj=equipment, changes={"Export": ["", "Fiche équipement (PDF)"]})
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="fiche-{equipment.code}.pdf"'
    return response
