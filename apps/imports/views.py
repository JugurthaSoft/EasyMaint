from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_capability
from apps.condition.importer import check_upload
from apps.core.models import AuditLog
from apps.core.services import log_action

from .importers import IMPORTERS, ORDER
from .models import DataImport

PREVIEW = 100


class UploadForm(forms.Form):
    file = forms.FileField(label=gettext_lazy("Fichier Excel (.xlsx) ou CSV"), widget=forms.FileInput(attrs={"accept": ".xlsx,.xlsm,.csv,.txt"}))
    update_existing = forms.BooleanField(label=gettext_lazy("Mettre à jour les fiches existantes (même code ou référence)"), required=False)

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        check_upload(uploaded)
        return uploaded


def _guard(request):
    if request.user.tenant_id is None:
        raise Http404
    require_capability(request.user, "imports.run")


def _available(request):
    """Types d'import accessibles : les articles et fournisseurs supposent le module Magasin."""
    from django.apps import apps as django_apps

    kinds = list(ORDER)
    if not django_apps.is_installed("apps.inventory"):
        kinds = [k for k in kinds if k not in ("articles", "fournisseurs")]
    return kinds


@login_required
def home(request):
    _guard(request)
    kinds = _available(request)
    form = UploadForm()
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind not in kinds:
            raise Http404
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            imp = DataImport(kind=kind, original_name=uploaded.name[:255], update_existing=form.cleaned_data["update_existing"],
                             created_by=request.user, tenant=request.tenant)
            imp.file = uploaded
            imp.save()
            log_action(AuditLog.Action.CREATE, request=request, obj=imp, changes={_("Fichier"): ["", imp.original_name]})
            return redirect(imp)
    cards = [(kind, IMPORTERS[kind]()) for kind in kinds]
    return render(request, "imports/home.html", {"cards": cards, "form": form, "imports": DataImport.objects.select_related("created_by")[:50]})


@login_required
def template(request, kind):
    _guard(request)
    if kind not in _available(request):
        raise Http404
    response = HttpResponse(IMPORTERS[kind]().template(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="modele-import-{kind}.xlsx"'
    return response


def _analyse(imp):
    importer = IMPORTERS[imp.kind]()
    with imp.file.open("rb") as handle:
        return importer, importer.analyse(handle, imp.original_name, update_existing=imp.update_existing)


def _errors(analysis):
    return [{"line": row.line, "label": row.label, "messages": row.messages} for row in analysis.errors][:500]


@login_required
def detail(request, pk):
    _guard(request)
    imp = get_object_or_404(DataImport.objects.select_related("created_by"), pk=pk)
    context = {"imp": imp}
    if imp.status == DataImport.Status.DRAFT:
        try:
            _importer, analysis = _analyse(imp)
        except ValidationError as error:
            context["read_error"] = " ".join(error.messages)
        else:
            context.update({
                "analysis": analysis, "preview": [row for row in analysis.rows if not row.messages][:PREVIEW],
                "creates": analysis.count("create"), "updates": analysis.count("update"), "skips": analysis.count("skip"),
                "error_rows": analysis.errors[:500],
            })
    return render(request, "imports/detail.html", context)


@login_required
@require_POST
def confirm(request, pk):
    _guard(request)
    with transaction.atomic():
        imp = get_object_or_404(DataImport.objects.select_for_update(), pk=pk)
        if imp.status != DataImport.Status.DRAFT:
            messages.error(request, _("Cet import a déjà été traité."))
            return redirect(imp)
        try:
            importer, analysis = _analyse(imp)
            if analysis.missing_columns or not analysis.valid:
                raise ValidationError(_("Rien à importer."))
            created, updated = importer.execute(analysis, request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect(imp)
        imp.status, imp.imported_at = DataImport.Status.DONE, timezone.now()
        imp.total_rows, imp.created_count, imp.updated_count = analysis.total, created, updated
        imp.skipped, imp.rejected, imp.errors = analysis.count("skip"), len(analysis.errors), _errors(analysis)
        imp.save()
    log_action(AuditLog.Action.UPDATE, request=request, obj=imp,
               changes={_("Import"): ["", _("%(c)s créées, %(u)s mises à jour") % {"c": created, "u": updated}]})
    messages.success(request, _("%(c)s fiche(s) créée(s), %(u)s mise(s) à jour, %(s)s ignorée(s), %(r)s refusée(s).") % {
        "c": created, "u": updated, "s": imp.skipped, "r": imp.rejected})
    return redirect(imp)


@login_required
@require_POST
def cancel(request, pk):
    _guard(request)
    imp = get_object_or_404(DataImport, pk=pk, status=DataImport.Status.DRAFT)
    imp.status = DataImport.Status.CANCELLED
    imp.save(update_fields=["status", "updated_at"])
    messages.info(request, _("Import abandonné."))
    return redirect("imports:home")


@login_required
def original(request, pk):
    _guard(request)
    imp = get_object_or_404(DataImport, pk=pk)
    return FileResponse(imp.file.open("rb"), as_attachment=True, filename=imp.original_name)
