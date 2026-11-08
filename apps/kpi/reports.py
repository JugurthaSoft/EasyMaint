"""Rapport mensuel de maintenance : PDF produit le 1er de chaque mois pour le mois écoulé, conservé dans l'application."""
import logging
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.formatting import format_money, format_number, month_name
from apps.core.models import Tenant
from apps.core.pdf import document
from apps.core.tenancy import tenant_context
from apps.finance import selectors as finance

from . import selectors
from .models import MonthlyReport

logger = logging.getLogger("easymaint")


def month_bounds(year, month):
    first = date(year, month, 1)
    return first, date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


def previous_month(today=None):
    today = today or timezone.localdate()
    last = today.replace(day=1) - timedelta(days=1)
    return last.year, last.month


def build_pdf(tenant, year, month):
    start, end = month_bounds(year, month)
    money = lambda value: format_money(value, tenant.currency_code, tenant.currency_decimals)  # noqa: E731
    hours = lambda value, n=1: "—" if value is None else f"{format_number(value, n)} h"  # noqa: E731
    pct = lambda value: "—" if value is None else f"{format_number(value, 1)} %"  # noqa: E731
    data = selectors.compute(start=start, end=end)
    rel, prev = data["rel"], data["preventive"]
    records = finance.cost_records(start, end)
    sections = [{
        "title": gettext("Indicateurs du mois"),
        "kv": [
            ("MTBF", hours(rel.mtbf, 0)), ("MTTR", hours(rel.mttr)),
            (gettext("Disponibilité opérationnelle"), pct(rel.availability)), (gettext("Disponibilité intrinsèque"), pct(rel.intrinsic)),
            (gettext("Pannes (dont avec arrêt)"), f"{rel.failures} ({rel.failures_stopped})"), (gettext("Durée des arrêts"), hours(rel.downtime_all)),
            (gettext("Préventif réalisé"), f"{pct(prev['realization_rate'])} ({prev['realized']}/{prev['due']})"),
            (gettext("Respect du planning"), pct(prev["on_time_rate"])),
            (gettext("Taux de correctif"), pct(data["corrective_rate"])), (gettext("OT clos"), str(data["closed_count"])),
            (gettext("Backlog (fin de mois)"), hours(data["backlog_hours"], 0)), (gettext("OT en retard (à l'édition)"), str(data["late"])),
            (gettext("Coût de maintenance"), money(data["cost"])), (gettext("Pièces consommées"), money(data["parts"])),
        ],
    }]
    by_kind = finance.group(records, "type")
    sections.append({"title": gettext("Coûts par type de maintenance"), "table": (
        [gettext("Type"), gettext("Main-d'œuvre"), gettext("Pièces"), gettext("Prestations"), gettext("Autres"), gettext("Total")],
        [[str(r["label"]), money(r["labour"]), money(r["parts"]), money(r["external"]), money(r["other"]), money(r["total"])] for r in by_kind],
        [2.4, 1.6, 1.6, 1.6, 1.6, 1.8], 1)})
    by_unit = finance.group(records, "unite")
    sections.append({"title": gettext("Coûts par unité"), "table": (
        [gettext("Unité"), gettext("Total"), gettext("Part")], [[str(r["label"]), money(r["total"]), f"{format_number(r['share'], 1)} %"] for r in by_unit], [5, 2, 1.2], 1)})
    sections.append({"title": gettext("Équipements les plus défaillants"), "table": (
        [gettext("Équipement"), gettext("Pannes"), gettext("Arrêts pour panne"), "MTTR"],
        [[f"{r['equipment'].code} · {r['equipment'].designation}", str(r["rel"].failures), hours(r["rel"].downtime_failure), hours(r["rel"].mttr)]
         for r in data["top_failures"]], [5, 1, 1.6, 1.2], 1)})
    sections.append({"title": gettext("Équipements les plus coûteux"), "table": (
        [gettext("Équipement"), gettext("Coût")], [[f"{r['equipment'].code} · {r['equipment'].designation}", money(r["cost"])] for r in data["top_costs"]], [6, 2], 1)})
    sections.append({"title": gettext("Définitions"), "text": "\n".join(f"{label} : {text}" for key, label, text in selectors.DEFINITIONS
                                                            if key in ("tr", "arret", "panne", "mtbf", "mttr", "dispo", "dispo_i"))})
    return document(company=tenant.name, title=gettext("Rapport mensuel de maintenance"), reference=f"{month_name(month)} {year}",
                    subtitle=gettext("Du %(start)s au %(end)s") % {"start": f"{start:%d/%m/%Y}", "end": f"{end:%d/%m/%Y}"}, sections=sections,
                    generated=gettext("produit le %(date)s") % {"date": f"{timezone.localtime():%d/%m/%Y %H:%M}"})


@transaction.atomic
def generate(tenant, year, month, *, user=None):
    """Produit (ou remplace) le rapport du mois. À appeler dans le contexte de l'entreprise."""
    content = build_pdf(tenant, year, month)
    report = MonthlyReport.objects.filter(year=year, month=month).first() or MonthlyReport(year=year, month=month, tenant=tenant)
    if report.pk and report.file:
        report.file.delete(save=False)
    report.generated_by = user
    report.file.save(f"rapport-maintenance-{year}-{month:02d}.pdf", ContentFile(content), save=False)
    report.save()
    return report


def generate_missing_for_all_tenants(today=None):
    """Planificateur : rapport du mois écoulé pour chaque entreprise active qui ne l'a pas encore."""
    year, month = previous_month(today)
    created = 0
    for tenant in Tenant.objects.filter(is_active=True):
        with tenant_context(tenant):
            if MonthlyReport.objects.filter(year=year, month=month).exists():
                continue
            try:
                generate(tenant, year, month)
                created += 1
            except Exception:
                logger.exception("Échec du rapport mensuel %s/%s pour %s", month, year, tenant.code)
    return created
