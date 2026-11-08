import io

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.assets.models import EquipmentFamily
from apps.core.formatting import format_number
from apps.core.models import AuditLog
from apps.core.services import log_action
from apps.core.tenancy import get_current_tenant
from apps.finance import selectors as finance
from apps.finance.pdf import table_report
from apps.finance.views import _filters, _money, _subtitle
from apps.workorders.models import WorkOrder

from . import selectors


def _hours(value, decimals=1):
    return "—" if value is None else f"{format_number(value, decimals)} h"


def _pct(value):
    return "—" if value is None else f"{format_number(value, 1)} %"


def _compute(params):
    f = _filters(params)
    data = selectors.compute(start=f["start"], end=f["end"], unit=f["unit"], family=f["family"], equipment=f["equipment"], kind=f["kind"])
    return f, data


class KpiView(CapabilityRequiredMixin, TemplateView):
    required_capability = "kpi.view"
    template_name = "kpi/indicators.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f, data = _compute(self.request.GET)
        trend = selectors.trend(end=f["end"], unit=f["unit"], family=f["family"], equipment=f["equipment"])
        kinds = dict(WorkOrder.Kind.choices)
        context.update({
            "f": f, "d": data, "rel": data["rel"], "query": self.request.GET.urlencode(),
            "units": finance.units(), "families": EquipmentFamily.objects.filter(parent__isnull=True).order_by("name"),
            "kinds": finance.kind_labels().items(),
            "trend": {
                "labels": [row["label"] for row in trend], "failures": [row["failures"] for row in trend],
                "mtbf": [row["mtbf"] for row in trend], "mttr": [row["mttr"] for row in trend],
                "availability": [row["availability"] for row in trend], "cost": [row["cost"] for row in trend],
            },
            "split": {"labels": [str(kinds.get(k, k)) for k in data["by_kind"]], "values": list(data["by_kind"].values())},
            "units_chart": {"labels": list(data["by_unit"].keys()), "values": list(data["by_unit"].values())},
            "kind_rows": [(kinds.get(k, k), n, data["hours_by_kind"].get(k)) for k, n in data["by_kind"].most_common()],
        })
        return context


class DefinitionsView(CapabilityRequiredMixin, TemplateView):
    required_capability = "kpi.view"
    template_name = "kpi/definitions.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "definitions": selectors.DEFINITIONS}


def _rows(data):
    rows = []
    for row in data["table"]:
        rel = row["rel"]
        rows.append([f"{row['equipment'].code} · {row['equipment'].designation}", format_number(rel.required, 0), str(rel.failures),
                     str(rel.failures_stopped), _hours(rel.downtime_all), _hours(rel.mtbf, 0), _hours(rel.mttr), _pct(rel.availability),
                     _money(row["cost"])])
    return rows


def headers():
    return [str(h) for h in HEADERS]


HEADERS = [gettext_lazy("Équipement"), gettext_lazy("Temps requis (h)"), gettext_lazy("Pannes"), gettext_lazy("dont avec arrêt"), gettext_lazy("Arrêts"), "MTBF", "MTTR", gettext_lazy("Disponibilité"), gettext_lazy("Coût")]


def _summary(data):
    rel, prev = data["rel"], data["preventive"]
    return [
        ("MTBF", _hours(rel.mtbf, 0)), ("MTTR", _hours(rel.mttr)), (gettext("Durée moyenne d'arrêt par panne"), _hours(rel.mean_stop)),
        (gettext("Disponibilité opérationnelle"), _pct(rel.availability)), (gettext("Disponibilité intrinsèque"), _pct(rel.intrinsic)),
        (gettext("Pannes (dont avec arrêt)"), f"{rel.failures} ({rel.failures_stopped})"), (gettext("Durée totale des arrêts"), _hours(rel.downtime_all)),
        (gettext("Taux de réalisation du préventif"), _pct(prev["realization_rate"])), (gettext("Respect du planning"), _pct(prev["on_time_rate"])),
        (gettext("Taux de correctif (nombre)"), _pct(data["corrective_rate"])), (gettext("Taux de correctif (heures)"), _pct(data["corrective_hours_rate"])),
        (gettext("Backlog"), gettext("%(hours)s (%(days)s jours-homme)") % {"hours": _hours(data["backlog_hours"], 0), "days": format_number(data["backlog_days"], 1)}),
        (gettext("OT en retard"), str(data["late"])), (gettext("Consommation de pièces"), _money(data["parts"])),
        (gettext("Coût de maintenance"), _money(data["cost"])), (gettext("Valeur du stock"), _money(data["stock_value"])),
    ]


@login_required
def kpi_export(request):
    require_capability(request.user, "kpi.view")
    from openpyxl import Workbook
    from openpyxl.styles import Font

    f, data = _compute(request.GET)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = gettext("Indicateurs")
    sheet.append([gettext("Indicateurs de maintenance"), _subtitle(f)])
    sheet.append([])
    for label, value in _summary(data):
        sheet.append([label, value])
    sheet.column_dimensions["A"].width, sheet.column_dimensions["B"].width = 38, 34
    detail = workbook.create_sheet(gettext("Par équipement"))
    detail.append(headers())
    for cell in detail[1]:
        cell.font = Font(bold=True)
    for row in data["table"]:
        rel = row["rel"]
        detail.append([f"{row['equipment'].code} · {row['equipment'].designation}", float(rel.required), rel.failures, rel.failures_stopped,
                       round(float(rel.downtime_all), 1), None if rel.mtbf is None else round(float(rel.mtbf), 0),
                       None if rel.mttr is None else round(float(rel.mttr), 1),
                       None if rel.availability is None else round(float(rel.availability), 1), float(row["cost"])])
    detail.column_dimensions["A"].width = 40
    definitions = workbook.create_sheet(gettext("Définitions"))
    for _key, label, text in selectors.DEFINITIONS:
        definitions.append([str(label), str(text)])
    definitions.column_dimensions["A"].width, definitions.column_dimensions["B"].width = 34, 120
    buffer = io.BytesIO()
    workbook.save(buffer)
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Indicateurs (Excel)"]})
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="indicateurs-maintenance-{timezone.localdate():%Y%m%d}.xlsx"'
    return response


@login_required
def kpi_pdf(request):
    require_capability(request.user, "kpi.view")
    f, data = _compute(request.GET)
    content = table_report(
        company=str(get_current_tenant()), title=_("Indicateurs de maintenance"), subtitle=_subtitle(f),
        headers=[_("Indicateur"), _("Valeur")], rows=[[label, value] for label, value in _summary(data)], numeric_from=1,
        widths=[1.6, 1], orientation="landscape",
        sections=[(_("Par équipement"), headers(), _rows(data), [4, 1.2, 0.8, 1, 1, 1, 1, 1.1, 1.4], 1)],
        notes=[f"{label} : {text}" for key, label, text in selectors.DEFINITIONS if key in ("tr", "panne", "mtbf", "mttr", "dispo", "dispo_i")],
        generated=_("édité le %(d)s") % {"d": timezone.localtime().strftime("%d/%m/%Y %H:%M")},
    )
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Indicateurs (PDF)"]})
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="indicateurs-maintenance-{timezone.localdate():%Y%m%d}.pdf"'
    return response


class ReportListView(CapabilityRequiredMixin, TemplateView):
    required_capability = "kpi.view"
    template_name = "kpi/reports.html"

    def get_context_data(self, **kwargs):
        from apps.core.formatting import month_name

        from .models import MonthlyReport
        from .reports import previous_month

        context = super().get_context_data(**kwargs)
        reports = list(MonthlyReport.objects.select_related("generated_by"))
        for report in reports:
            report.label = f"{month_name(report.month)} {report.year}"
        year, month = previous_month()
        context.update({"reports": reports, "default_month": f"{year}-{month:02d}"})
        return context


@login_required
def report_file(request, pk):
    require_capability(request.user, "kpi.view")
    from django.http import FileResponse
    from django.shortcuts import get_object_or_404

    from .models import MonthlyReport

    report = get_object_or_404(MonthlyReport, pk=pk)
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", f"Rapport mensuel {report}"]})
    return FileResponse(report.file.open("rb"), content_type="application/pdf",
                        filename=f"rapport-maintenance-{report.year}-{report.month:02d}.pdf")


@login_required
def report_generate(request):
    """Produit (ou refait) le rapport d'un mois passé ou du mois en cours."""
    from django.contrib import messages
    from django.shortcuts import redirect
    require_capability(request.user, "kpi.view")
    if request.method != "POST":
        return redirect("kpi:reports")
    from .reports import generate

    try:
        year, month = (int(part) for part in (request.POST.get("mois") or "").split("-"))
        if not (2000 <= year <= 2100 and 1 <= month <= 12) or (year, month) > (timezone.localdate().year, timezone.localdate().month):
            raise ValueError
    except ValueError:
        messages.error(request, _("Choisissez un mois écoulé ou le mois en cours."))
        return redirect("kpi:reports")
    report = generate(request.tenant, year, month, user=request.user)
    log_action(AuditLog.Action.CREATE, request=request, changes={_("Rapport mensuel"): ["", str(report)]})
    messages.success(request, _("Rapport %(m)s produit.") % {"m": str(report)})
    return redirect("kpi:reports")
