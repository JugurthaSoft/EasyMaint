"""
Coûts réels de maintenance.

Sources (définitions affichées dans l'application et documentées dans docs/architecture.md) :
- OT **validés** (coûts figés à la validation), datés de leur **fin réelle** des travaux
  (à défaut de leur validation) ;
- sorties de stock **hors OT** imputées à un équipement (pièces seulement).
Rattachement : unité = premier niveau « Unité » au-dessus de la localisation de l'équipement ;
famille = famille de premier niveau de l'équipement.
"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.assets.models import Equipment, EquipmentFamily, Location
from apps.core.formatting import month_abbr, month_abbreviations
from apps.workorders.models import WorkOrder

from .models import Budget

ZERO = Decimal("0")
CATEGORIES = [
    ("labour", gettext_lazy("Main-d'œuvre")), ("parts", gettext_lazy("Pièces")),
    ("external", gettext_lazy("Prestations externes")), ("other", gettext_lazy("Autres dépenses")),
]
STOCK_KIND = "stock"
GROUPINGS = [
    ("equipement", gettext_lazy("Équipement")), ("unite", gettext_lazy("Unité")), ("famille", gettext_lazy("Famille")),
    ("type", gettext_lazy("Type de maintenance")), ("mois", gettext_lazy("Mois")),
]


def kind_labels():
    labels = dict(WorkOrder.Kind.choices)
    labels[STOCK_KIND] = _("Pièces hors OT")
    return labels


@dataclass
class CostRecord:
    day: date
    equipment_id: int
    unit_id: int | None
    family_id: int | None
    kind: str
    labour: Decimal
    parts: Decimal
    external: Decimal
    other: Decimal
    reference: str
    url: str

    @property
    def total(self):
        return self.labour + self.parts + self.external + self.other


def location_units():
    """{id de localisation: unité (Location de type « Unité ») ou None}, en une requête."""
    locations = {location.pk: location for location in Location.objects.all()}
    result = {}
    for pk, location in locations.items():
        node, seen = location, set()
        while node is not None and node.pk not in seen and node.kind != Location.Kind.WORKSHOP:
            seen.add(node.pk)
            node = locations.get(node.parent_id)
        result[pk] = node
    return result


def family_roots():
    families = {family.pk: family for family in EquipmentFamily.objects.all()}
    roots = {}
    for pk, family in families.items():
        node, seen = family, set()
        while node.parent_id and node.parent_id in families and node.pk not in seen:
            seen.add(node.pk)
            node = families[node.parent_id]
        roots[pk] = node
    return roots


def bounds(start, end):
    """Dates incluses → intervalle [début 00:00, lendemain de la fin 00:00) dans le fuseau courant."""
    tz = timezone.get_current_timezone()
    return datetime.combine(start, time.min, tzinfo=tz), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)


def cost_records(start, end, *, unit=None, family=None, kind="", equipment=None):
    from apps.inventory.models import StockMovement

    low, high = bounds(start, end)
    units, roots = location_units(), family_roots()
    equipment_info = {e.pk: e for e in Equipment.objects.only("pk", "location_id", "family_id", "code")}
    records = []
    orders = (WorkOrder.objects.filter(status=WorkOrder.Status.VALIDATED)
              .annotate(cost_at=Coalesce("finished_at", "validated_at"))
              .filter(cost_at__gte=low, cost_at__lt=high).order_by("cost_at"))
    for wo in orders:
        eq = equipment_info.get(wo.equipment_id)
        unit_obj = units.get(eq.location_id) if eq else None
        root = roots.get(eq.family_id) if eq else None
        records.append(CostRecord(
            day=timezone.localtime(wo.cost_at).date(), equipment_id=wo.equipment_id, unit_id=unit_obj.pk if unit_obj else None,
            family_id=root.pk if root else None, kind=wo.kind, labour=wo.labour_cost, parts=wo.parts_cost,
            external=wo.external_cost, other=wo.other_cost, reference=wo.number, url=wo.get_absolute_url(),
        ))
    issues = StockMovement.objects.filter(kind=StockMovement.Kind.ISSUE, work_order__isnull=True, equipment__isnull=False,
                                          moved_at__gte=low, moved_at__lt=high)
    for movement in issues:
        eq = equipment_info.get(movement.equipment_id)
        unit_obj = units.get(eq.location_id) if eq else None
        root = roots.get(eq.family_id) if eq else None
        records.append(CostRecord(
            day=timezone.localtime(movement.moved_at).date(), equipment_id=movement.equipment_id,
            unit_id=unit_obj.pk if unit_obj else None, family_id=root.pk if root else None, kind=STOCK_KIND,
            labour=ZERO, parts=-movement.value, external=ZERO, other=ZERO, reference=movement.number,
            url=reverse("inventory:movement_list") + f"?q={movement.number}",
        ))
    if unit is not None:
        records = [r for r in records if r.unit_id == unit.pk]
    if family is not None:
        records = [r for r in records if r.family_id == family.pk]
    if kind:
        records = [r for r in records if r.kind == kind]
    if equipment is not None:
        records = [r for r in records if r.equipment_id == equipment.pk]
    return records


def totals(records):
    result = {name: sum((getattr(r, name) for r in records), ZERO) for name, _label in CATEGORIES}
    result["total"] = sum(result.values(), ZERO)
    result["count"] = sum(1 for r in records if r.kind != STOCK_KIND)
    return result


def month_label(year, month):
    return f"{month_abbr(month)} {year}"


def group(records, by):
    """Lignes agrégées, de la plus coûteuse à la moins coûteuse (sauf « mois », chronologique)."""
    labels, urls = {}, {}
    if by == "equipement":
        for e in Equipment.objects.filter(pk__in={r.equipment_id for r in records}):
            labels[e.pk], urls[e.pk] = f"{e.code} · {e.designation}", e.get_absolute_url()
        key = lambda r: r.equipment_id  # noqa: E731
    elif by == "unite":
        labels = {u.pk: u.name for u in Location.objects.filter(pk__in={r.unit_id for r in records if r.unit_id})}
        labels[None] = _("Hors unité")
        key = lambda r: r.unit_id  # noqa: E731
    elif by == "famille":
        labels = {f.pk: f.name for f in EquipmentFamily.objects.filter(pk__in={r.family_id for r in records if r.family_id})}
        labels[None] = _("Sans famille")
        key = lambda r: r.family_id  # noqa: E731
    elif by == "type":
        labels = kind_labels()
        key = lambda r: r.kind  # noqa: E731
    else:
        key = lambda r: (r.day.year, r.day.month)  # noqa: E731
    buckets = OrderedDict()
    for record in records:
        buckets.setdefault(key(record), []).append(record)
    grand = sum((r.total for r in records), ZERO)
    rows = []
    for k, items in buckets.items():
        row = totals(items)
        row["key"] = k
        row["label"] = month_label(*k) if by == "mois" else labels.get(k, str(k))
        row["url"] = urls.get(k, "")
        row["share"] = (row["total"] / grand * 100) if grand else ZERO
        rows.append(row)
    if by == "mois":
        rows.sort(key=lambda row: row["key"])
    else:
        rows.sort(key=lambda row: (-row["total"], str(row["label"])))
    return rows


def monthly(records, year):
    """Total par mois (12 valeurs) d'une année."""
    values = [ZERO] * 12
    for record in records:
        if record.day.year == year:
            values[record.day.month - 1] += record.total
    return values


def units():
    return Location.objects.filter(kind=Location.Kind.WORKSHOP).order_by("name")


def budget_table(year):
    """Par unité : budget et réel mensuels, totaux, écart et taux de consommation."""
    records = cost_records(date(year, 1, 1), date(year, 12, 31))
    budgets = {b.unit_id: b for b in Budget.objects.filter(year=year)}
    rows = []
    for unit in units():
        budget = budgets.get(unit.pk)
        planned = budget.months if budget else [ZERO] * 12
        actual = monthly([r for r in records if r.unit_id == unit.pk], year)
        rows.append(_budget_row(unit.name, unit, budget, planned, actual))
    outside = [r for r in records if r.unit_id is None]
    if outside:
        rows.append(_budget_row(_("Hors unité"), None, None, [ZERO] * 12, monthly(outside, year)))
    planned_total = [sum((row["planned"][i] for row in rows), ZERO) for i in range(12)]
    actual_total = [sum((row["actual"][i] for row in rows), ZERO) for i in range(12)]
    return rows, _budget_row(_("Total"), None, None, planned_total, actual_total)


def _budget_row(label, unit, budget, planned, actual):
    planned_sum, actual_sum = sum(planned, ZERO), sum(actual, ZERO)
    today = timezone.localdate()
    return {
        "label": label, "unit": unit, "budget": budget, "planned": planned, "actual": actual,
        "planned_total": planned_sum, "actual_total": actual_sum, "gap": planned_sum - actual_sum,
        "rate": (actual_sum / planned_sum * 100) if planned_sum else None,
        "months": list(zip(month_abbreviations(), planned, actual, strict=True)),
        "today_month": today.month,
    }


def equipment_history(equipment):
    """Historique financier d'un équipement : par année, catégories et OT les plus coûteux."""
    first = WorkOrder.objects.filter(equipment=equipment).order_by("created_at").values_list("created_at", flat=True).first()
    start = timezone.localtime(first).date().replace(month=1, day=1) if first else timezone.localdate().replace(month=1, day=1)
    records = cost_records(start, timezone.localdate(), equipment=equipment)
    years = group(records, "mois")
    by_year = OrderedDict()
    for row in years:
        year = row["key"][0]
        acc = by_year.setdefault(year, {name: ZERO for name in ("labour", "parts", "external", "other", "total")} | {"count": 0})
        for name in ("labour", "parts", "external", "other", "total", "count"):
            acc[name] += row[name]
    top = sorted((r for r in records if r.kind != STOCK_KIND), key=lambda r: -r.total)[:5]
    return {"years": list(by_year.items()), "total": totals(records), "top": top, "by_kind": group(records, "type")}


def months():
    """Mois abrégés de l'année, dans la langue active (janv. … déc. / Jan … Dec)."""
    return month_abbreviations()
