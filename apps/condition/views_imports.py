"""Écrans d'import de mesures : envoi du fichier, correspondance des colonnes, aperçu, confirmation, historique."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.core.models import AuditLog
from apps.core.services import log_action

from . import importer
from .models import ImportProfile, MeasurementImport, Parameter

PREVIEW_ROWS = 50
SAMPLE_ROWS = 3


class UploadForm(forms.Form):
    file = forms.FileField(label=gettext_lazy("Fichier CSV ou Excel"), widget=forms.FileInput(attrs={"accept": ".csv,.txt,.xlsx,.xlsm"}))
    profile = forms.ModelChoiceField(
        label=gettext_lazy("Format"), queryset=ImportProfile.objects.none(), required=False,
        empty_label=gettext_lazy("— Détection automatique —"),
        help_text=gettext_lazy("Correspondance des colonnes mémorisée lors d'un import précédent."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile"].queryset = ImportProfile.objects.all()

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        importer.check_upload(uploaded)
        return uploaded


def _check(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied
    require_capability(request.user, "imports.run")


class ImportListView(CapabilityRequiredMixin, ListView):
    required_capability = "imports.run"
    template_name = "condition/import_list.html"
    context_object_name = "imports"
    paginate_by = 30

    def get_queryset(self):
        return MeasurementImport.objects.select_related("profile", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or UploadForm()
        context["profiles"] = ImportProfile.objects.all()
        context["max_rows"] = importer.MAX_ROWS
        return context

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            try:
                table = importer.read_table(uploaded, uploaded.name)
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                uploaded.seek(0)
                profile = form.cleaned_data["profile"]
                mapping = (importer.clean_mapping(profile.mapping, table.headers) if profile
                           else importer.guess_mapping(table.headers))
                imp = MeasurementImport.objects.create(
                    file=uploaded, original_name=uploaded.name[:255], profile=profile, mapping=mapping,
                    total_rows=len(table.rows), created_by=request.user,
                )
                if not importer.mapping_problems(mapping):
                    importer.store_analysis(imp, importer.analyse_table(table, mapping))
                log_action(AuditLog.Action.CREATE, request=request, obj=imp,
                           changes={_("Fichier"): ["", imp.original_name]})
                if table.truncated:
                    messages.warning(request, _("Seules les %(n)s premières lignes seront importées : découpez le fichier.") % {"n": importer.MAX_ROWS})
                return redirect(imp)
        self.object_list = self.get_queryset()
        return self.render_to_response(self.get_context_data(form=form))


class ImportDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "imports.run"
    template_name = "condition/import_detail.html"
    context_object_name = "imp"

    def get_queryset(self):
        return MeasurementImport.objects.select_related("profile", "created_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        imp = self.object
        context["sessions"] = imp.sessions.select_related("equipment", "technician").order_by("measured_at")[:200]
        if imp.status != MeasurementImport.Status.DRAFT:
            return context
        try:
            with imp.file.open("rb") as handle:
                table = importer.read_table(handle, imp.original_name)
        except (ValidationError, OSError) as exc:
            context["read_error"] = " ".join(getattr(exc, "messages", [str(exc)]))
            return context
        mapping = importer.clean_mapping(imp.mapping, table.headers)
        columns, values = mapping["columns"], mapping["values"]
        assigned = {header: code for code, header in columns.items()}
        context["field_rows"] = [
            {"code": code, "label": label, "required": required, "selected": columns.get(code, "")}
            for code, label, required in importer.FIELDS
        ]
        context["headers"] = [
            {
                "index": index, "name": header, "field": assigned.get(header, ""), "parameter": values.get(header, ""),
                "samples": [importer._cell_text(cells[index]) if index < len(cells) else "" for _line, cells in table.rows[:SAMPLE_ROWS]],
            }
            for index, header in enumerate(table.headers)
        ]
        context["parameters"] = Parameter.objects.filter(is_active=True).order_by("code")
        context["problems"] = importer.mapping_problems(mapping)
        context["truncated"] = table.truncated
        if not context["problems"]:
            analysis = importer.analyse_table(table, mapping)
            new_items = analysis.new_items
            context.update({
                "analysis": analysis,
                "preview": new_items[:PREVIEW_ROWS],
                "new_count": len(new_items),
                "more_count": max(0, len(new_items) - PREVIEW_ROWS),
                "errors": analysis.errors[:importer.MAX_STORED_ERRORS],
                "too_many": len(new_items) > importer.MAX_MEASUREMENTS,
            })
        return context


def _draft(request, pk):
    _check(request)
    imp = get_object_or_404(MeasurementImport, pk=pk)
    if imp.status != MeasurementImport.Status.DRAFT:
        messages.error(request, _("Cet import a déjà été traité."))
        return None, redirect(imp)
    return imp, None


@login_required
@require_POST
def import_mapping(request, pk):
    """Enregistre la correspondance des colonnes (et, au choix, la mémorise comme format)."""
    imp, response = _draft(request, pk)
    if response:
        return response
    with imp.file.open("rb") as handle:
        table = importer.read_table(handle, imp.original_name)
    headers = table.headers
    columns, values, errors = {}, {}, []
    codes = set(Parameter.objects.values_list("code", flat=True))

    def header_at(raw):
        try:
            return headers[int(raw)]
        except (TypeError, ValueError, IndexError):
            return None

    for code in importer.FIELD_CODES:
        header = header_at(request.POST.get(f"f-{code}"))
        if header is not None:
            if header in columns.values():
                errors.append(_("La colonne « %(h)s » est attribuée à deux champs.") % {"h": header})
            columns[code] = header
    for index, header in enumerate(headers):
        code = request.POST.get(f"h-{index}", "")
        if code and header not in columns.values():
            if code not in codes:
                errors.append(_("Paramètre inconnu pour la colonne « %(h)s ».") % {"h": header})
            else:
                values[header] = code
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect(imp)
    imp.mapping = {"columns": columns, "values": values}
    name = request.POST.get("profile_name", "").strip()[:150]
    if name:
        profile, created = ImportProfile.objects.get_or_create(name=name, defaults={"mapping": imp.mapping, "created_by": request.user})
        if not created:
            profile.mapping = imp.mapping
            profile.save(update_fields=["mapping", "updated_at"])
        log_action(AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE, request=request, obj=profile,
                   changes={_("Format"): ["", profile.name]})
        imp.profile = profile
        messages.success(request, _("Format « %(n)s » enregistré : il sera proposé lors des prochains imports.") % {"n": profile.name})
    imp.save(update_fields=["mapping", "profile", "updated_at"])
    if not importer.mapping_problems(imp.mapping):
        importer.store_analysis(imp, importer.analyse_table(table, imp.mapping))
    return redirect(imp)


@login_required
@require_POST
def import_confirm(request, pk):
    imp, response = _draft(request, pk)
    if response:
        return response
    try:
        imp = importer.execute(imp, user=request.user)
    except ValidationError as exc:
        for message in exc.messages:
            messages.error(request, message)
        return redirect(imp)
    log_action(AuditLog.Action.UPDATE, request=request, obj=imp,
               changes={_("Import"): ["", _("%(n)s mesures importées") % {"n": imp.imported}]})
    messages.success(request, _("%(n)s mesures importées en %(s)s tournées ; %(d)s doublons ignorés, %(r)s lignes refusées.") % {
        "n": imp.imported, "s": imp.sessions_created, "d": imp.skipped, "r": imp.rejected,
    })
    return redirect(imp)


@login_required
@require_POST
def import_cancel(request, pk):
    imp, response = _draft(request, pk)
    if response:
        return response
    imp.status = MeasurementImport.Status.CANCELLED
    imp.save(update_fields=["status", "updated_at"])
    log_action(AuditLog.Action.UPDATE, request=request, obj=imp, changes={_("Statut"): [_("À valider"), _("Abandonné")]})
    messages.info(request, _("Import abandonné. Le fichier reste consultable dans l'historique."))
    return redirect("condition:import_list")


@login_required
def import_file(request, pk):
    _check(request)
    imp = get_object_or_404(MeasurementImport, pk=pk)
    return FileResponse(imp.file.open("rb"), as_attachment=True, filename=imp.original_name)


@login_required
def import_template(request):
    _check(request)
    content = importer.build_template()
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Modèle d'import des mesures (Excel)"]})
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="modele-import-mesures-{timezone.localdate():%Y%m%d}.xlsx"'
    return response


@login_required
@require_POST
def profile_delete(request, pk):
    _check(request)
    profile = get_object_or_404(ImportProfile, pk=pk)
    log_action(AuditLog.Action.DELETE, request=request, obj=profile, changes={_("Format"): [profile.name, ""]})
    profile.delete()
    messages.info(request, _("Format supprimé."))
    return redirect("condition:import_list")
