import io
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.assets.models import Equipment, EquipmentFamily, Location
from apps.core.formatting import format_money, format_number
from apps.core.models import AuditLog
from apps.core.services import log_action
from apps.core.tenancy import get_current_tenant

from . import selectors
from .forms import BudgetForm
from .models import Budget
from .pdf import table_report


def _money(value):
    tenant = get_current_tenant()
    return format_money(value, getattr(tenant, "currency_code", "TND"), getattr(tenant, "currency_decimals", 3))


def _filters(params):
    today = timezone.localdate()
    start = parse_date(params.get("du") or "") or today.replace(month=1, day=1)
    end = parse_date(params.get("au") or "") or today
    if end < start:
        start, end = end, start
    by = params.get("regroupement") if params.get("regroupement") in dict(selectors.GROUPINGS) else "equipement"

    def pick(model, key, **extra):
        value = params.get(key) or ""
        return model.objects.filter(pk=int(value), **extra).first() if value.isdigit() else None

    return {
        "start": start, "end": end, "by": by,
        "unit": pick(Location, "unite", kind=Location.Kind.WORKSHOP),
        "family": pick(EquipmentFamily, "famille", parent__isnull=True),
        "equipment": pick(Equipment, "equipement_id"),
        "kind": params.get("type") if params.get("type") in selectors.kind_labels() else "",
    }


def _analysis(params):
    f = _filters(params)
    records = selectors.cost_records(f["start"], f["end"], unit=f["unit"], family=f["family"], kind=f["kind"], equipment=f["equipment"])
    return f, records, selectors.group(records, f["by"]), selectors.totals(records)


def _subtitle(f):
    parts = [_("Du %(a)s au %(b)s") % {"a": f["start"].strftime("%d/%m/%Y"), "b": f["end"].strftime("%d/%m/%Y")}]
    for key in ("unit", "family", "equipment"):
        if f[key] is not None:
            parts.append(str(f[key]))
    if f["kind"]:
        parts.append(str(selectors.kind_labels()[f["kind"]]))
    return " · ".join(parts)


DEFINITION = _(
    "Coûts réels : OT validés (coûts figés à la validation), datés de la fin des travaux, et sorties de stock hors OT "
    "imputées à un équipement. Pièces au coût moyen pondéré de sortie."
)


class CostsView(CapabilityRequiredMixin, TemplateView):
    required_capability = "costs.view"
    template_name = "finance/costs.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        f, records, rows, total = _analysis(self.request.GET)
        year = f["end"].year
        previous = selectors.cost_records(date(year - 1, 1, 1), date(year - 1, 12, 31), unit=f["unit"], family=f["family"],
                                          kind=f["kind"], equipment=f["equipment"])
        current = selectors.cost_records(date(year, 1, 1), date(year, 12, 31), unit=f["unit"], family=f["family"],
                                         kind=f["kind"], equipment=f["equipment"])
        top = rows[:15] if f["by"] != "mois" else rows
        params = self.request.GET.copy()
        context.update({
            "f": f, "rows": rows, "total": total, "categories": selectors.CATEGORIES, "groupings": selectors.GROUPINGS,
            "units": selectors.units(), "families": EquipmentFamily.objects.filter(parent__isnull=True).order_by("name"),
            "kinds": selectors.kind_labels().items(), "query": params.urlencode(), "definition": DEFINITION,
            "chart": {
                "labels": [str(row["label"])[:40] for row in top],
                "series": [{"label": str(label), "values": [float(row[name]) for row in top]} for name, label in selectors.CATEGORIES],
            },
            "trend": {
                "labels": selectors.months(), "year": year,
                "current": [float(v) for v in selectors.monthly(current, year)],
                "previous": [float(v) for v in selectors.monthly(previous, year - 1)],
            },
            "year_total": sum(selectors.monthly(current, year)), "previous_total": sum(selectors.monthly(previous, year - 1)),
        })
        return context


def _table(f, rows, total):
    headers = [str(dict(selectors.GROUPINGS)[f["by"]])] + [str(label) for _name, label in selectors.CATEGORIES] + [_("Total"), _("OT"), _("Part")]
    lines = [[str(row["label"])] + [_money(row[name]) for name, _label in selectors.CATEGORIES]
             + [_money(row["total"]), str(row["count"]), f"{format_number(row['share'], 1)} %"] for row in rows]
    totals = [_("Total")] + [_money(total[name]) for name, _label in selectors.CATEGORIES] + [_money(total["total"]), str(total["count"]), "100 %"]
    return headers, lines, totals


@login_required
def costs_export(request):
    require_capability(request.user, "costs.view")
    from openpyxl import Workbook
    from openpyxl.styles import Font

    f, _records, rows, total = _analysis(request.GET)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = gettext("Coûts")
    sheet.append([_("Coûts de maintenance"), _subtitle(f)])
    sheet.append([])
    headers = [str(dict(selectors.GROUPINGS)[f["by"]])] + [str(label) for _n, label in selectors.CATEGORIES] + [_("Total"), _("OT"), _("Part (%)")]
    sheet.append(headers)
    for cell in sheet[3]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([str(row["label"])] + [row[name] for name, _l in selectors.CATEGORIES] + [row["total"], row["count"], round(float(row["share"]), 1)])
    sheet.append([_("Total")] + [total[name] for name, _l in selectors.CATEGORIES] + [total["total"], total["count"], 100])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 42
    for column in "BCDEFGH":
        sheet.column_dimensions[column].width = 16
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Coûts de maintenance (Excel)"]})
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="couts-maintenance-{timezone.localdate():%Y%m%d}.xlsx"'
    return response


@login_required
def costs_pdf(request):
    require_capability(request.user, "costs.view")
    f, _records, rows, total = _analysis(request.GET)
    headers, lines, totals = _table(f, rows, total)
    content = table_report(
        company=str(get_current_tenant()), title=_("Coûts de maintenance par %(g)s") % {"g": str(dict(selectors.GROUPINGS)[f["by"]]).lower()},
        subtitle=_subtitle(f), headers=headers, rows=lines, totals=totals, notes=[DEFINITION],
        widths=[4.2, 1.6, 1.6, 1.6, 1.6, 1.8, 0.7, 0.8], generated=_("édité le %(d)s par %(u)s") % {
            "d": timezone.localtime().strftime("%d/%m/%Y %H:%M"), "u": request.user.get_full_name() or request.user.username},
    )
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Coûts de maintenance (PDF)"]})
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="couts-maintenance-{timezone.localdate():%Y%m%d}.pdf"'
    return response


def _year(request):
    value = request.GET.get("annee", "")
    return int(value) if value.isdigit() and 2000 <= int(value) <= 2100 else timezone.localdate().year


class BudgetView(CapabilityRequiredMixin, TemplateView):
    required_capability = "costs.view"
    template_name = "finance/budget.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year = _year(self.request)
        rows, total = selectors.budget_table(year)
        context.update({
            "year": year, "rows": rows, "total": total, "months": selectors.months(),
            "years": range(timezone.localdate().year + 1, timezone.localdate().year - 4, -1),
            "chart": {"labels": selectors.months(), "planned": [float(v) for v in total["planned"]], "actual": [float(v) for v in total["actual"]]},
            "is_current": year == timezone.localdate().year, "definition": DEFINITION,
        })
        return context


@login_required
def budget_edit(request, year, unit_pk):
    require_capability(request.user, "costs.manage")
    if not 2000 <= year <= 2100:
        raise Http404
    unit = get_object_or_404(Location, pk=unit_pk, kind=Location.Kind.WORKSHOP)
    budget = Budget.objects.filter(year=year, unit=unit).first() or Budget(year=year, unit=unit)
    creating = budget.pk is None
    before = budget.annual
    form = BudgetForm(request.POST or None, instance=budget)
    if request.method == "POST" and form.is_valid():
        budget = form.save(commit=False)
        if creating:
            budget.created_by = request.user
        budget.save()
        log_action(AuditLog.Action.CREATE if creating else AuditLog.Action.UPDATE, request=request, obj=budget,
                   changes={_("Budget %(y)s %(u)s") % {"y": year, "u": unit.name}: [_money(before) if not creating else "", _money(budget.annual)]})
        messages.success(request, _("Budget %(y)s de %(u)s enregistré : %(a)s.") % {"y": year, "u": unit.name, "a": _money(budget.annual)})
        return redirect(f"{reverse('finance:budget')}?annee={year}")
    return render(request, "finance/budget_form.html", {"form": form, "unit": unit, "year": year, "months": selectors.months(),
                                                         "month_fields": [form[name] for name in form.Meta.fields[:12]]})


@login_required
def budget_pdf(request):
    require_capability(request.user, "costs.view")
    year = _year(request)
    rows, total = selectors.budget_table(year)
    headers = [_("Unité"), ""] + selectors.months() + [_("Année")]
    lines = []
    for row in rows + [total]:
        lines.append([str(row["label"]), _("Budget")] + [format_number(v, 0) for v in row["planned"]] + [format_number(row["planned_total"], 0)])
        rate = f" ({format_number(row['rate'], 0)} %)" if row["rate"] is not None else ""
        lines.append(["", _("Réel")] + [format_number(v, 0) for v in row["actual"]] + [format_number(row["actual_total"], 0) + rate])
    tenant = get_current_tenant()
    content = table_report(
        company=str(tenant), title=_("Budget et dépenses de maintenance %(y)s") % {"y": year},
        subtitle=_("Montants en %(c)s, arrondis à l'unité. Réel = OT validés et sorties de stock hors OT.") % {"c": getattr(tenant, "currency_code", "TND")},
        headers=headers, rows=lines, notes=[DEFINITION], numeric_from=2, widths=[2.6, 0.9] + [1] * 12 + [1.8],
        generated=_("édité le %(d)s") % {"d": timezone.localtime().strftime("%d/%m/%Y %H:%M")},
    )
    log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", f"Budget {year} (PDF)"]})
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="budget-maintenance-{year}.pdf"'
    return response


def equipment_tab_context(request, equipment):
    """Onglet « Coûts » de la fiche équipement : historique financier complet."""
    history = selectors.equipment_history(equipment)
    return {"cost_history": history, "categories": selectors.CATEGORIES}
