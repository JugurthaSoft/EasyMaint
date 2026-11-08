"""
Indicateurs de maintenance, calculés sur les données réelles. Les définitions ci-dessous sont
reprises mot pour mot sur la page « Définitions des indicateurs » (DEFINITIONS).

- Temps requis (TR) d'un équipement = jours de fonctionnement de la période (selon ses jours
  par semaine, du lundi au samedi pour 6) × heures requises par jour.
- Arrêt : arrêt machine avec arrêt de production, compté seulement les jours de fonctionnement
  et au plus les heures requises de chaque jour (un arrêt de nuit ou de week-end ne réduit pas
  le temps requis qu'il ne recouvre pas).
- Panne : OT correctif terminé ou validé (cause de défaillance renseignée), daté de son début réel.
- MTBF = (TR − arrêts pour panne) ÷ nombre de pannes.
- MTTR = moyenne des durées de réparation (début réel → fin réelle) des pannes.
- Disponibilité opérationnelle = (TR − tous les arrêts) ÷ TR ; intrinsèque = (TR − arrêts pour panne) ÷ TR.
"""
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Equipment
from apps.finance import selectors as finance
from apps.workorders.models import Downtime, TimeEntry, WorkOrder

ZERO = Decimal("0")
DONE = (WorkOrder.Status.DONE, WorkOrder.Status.VALIDATED)

DEFINITIONS = [
    ("tr", _("Temps requis (TR)"), _(
        "Pour chaque équipement : nombre de jours de fonctionnement de la période (selon ses jours de fonctionnement par "
        "semaine : 5 = lundi au vendredi, 6 = lundi au samedi, 7 = tous les jours) × ses heures requises par jour. "
        "Équipements réformés exclus.")),
    ("arret", _("Arrêt"), _(
        "Arrêt machine enregistré avec arrêt de production (déclaration de panne, OT marqué « arrêt »). Seule la partie "
        "qui tombe un jour de fonctionnement est comptée, dans la limite des heures requises de ce jour. Un arrêt encore "
        "en cours est compté jusqu'à maintenant.")),
    ("panne", _("Panne"), _(
        "OT correctif terminé ou validé (la cause de défaillance est obligatoire pour le terminer), daté de son début réel "
        "(à défaut de sa création). Les pannes avec arrêt de production sont distinguées de celles sans arrêt.")),
    ("mtbf", _("MTBF — temps moyen entre défaillances"), _("(TR − durée des arrêts pour panne) ÷ nombre de pannes, en heures.")),
    ("mttr", _("MTTR — temps moyen de réparation"), _(
        "Moyenne, sur les pannes de la période, de la durée entre le début réel et la fin réelle de l'OT, en heures. "
        "La durée moyenne d'arrêt par panne (arrêts de production pour panne ÷ pannes avec arrêt) est affichée à côté.")),
    ("dispo", _("Disponibilité opérationnelle"), _("(TR − tous les arrêts de production : pannes, maintenance planifiée, autres) ÷ TR.")),
    ("dispo_i", _("Disponibilité intrinsèque"), _("(TR − arrêts de production pour panne uniquement) ÷ TR.")),
    ("prev", _("Taux de réalisation du préventif"), _(
        "OT préventifs terminés ou validés ÷ OT préventifs dont l'échéance d'origine tombe dans la période. Un OT annulé "
        "compte comme non réalisé.")),
    ("planning", _("Respect du planning"), _("OT préventifs réalisés au plus tard à leur échéance d'origine ÷ OT préventifs échus dans la période.")),
    ("correctif", _("Taux de correctif"), _(
        "OT correctifs ÷ ensemble des OT terminés ou validés dans la période (date de fin réelle), en nombre et en heures "
        "pointées.")),
    ("backlog", _("Backlog"), _("Somme des heures estimées des OT ouverts (non terminés) à la date du calcul ; en jours-homme : ÷ 8 h.")),
    ("retard", _("OT en retard"), _("OT ouverts dont l'échéance est dépassée à la date du calcul.")),
    ("pdr", _("Consommation de pièces"), _("Valeur des sorties de stock de la période (OT et hors OT), nette des retours, au coût moyen pondéré de sortie.")),
    ("stock", _("Valeur du stock"), _("Quantités en stock × coût moyen pondéré, à la date du calcul.")),
    ("cout", _("Coût de maintenance"), _("OT validés (date de fin des travaux) et sorties de stock hors OT imputées à un équipement.")),
]


def _aware(day, at=time.min):
    return datetime.combine(day, at, tzinfo=timezone.get_current_timezone())


def operating_days(equipment, start, end):
    days = equipment.operating_days_per_week or 7
    count, current = 0, start
    while current <= end:
        if current.weekday() < days:
            count += 1
        current += timedelta(days=1)
    return count


def required_hours(equipment, start, end):
    return Decimal(operating_days(equipment, start, end)) * (equipment.required_hours_per_day or ZERO)


def downtime_hours(event, equipment, start, end, now):
    """Heures d'arrêt comptées : jours de fonctionnement seulement, plafonnées aux heures requises par jour."""
    begin = max(event.started_at, _aware(start))
    finish = min(event.ended_at or now, _aware(end + timedelta(days=1)), now)
    if finish <= begin:
        return ZERO
    cap = equipment.required_hours_per_day or ZERO
    days = equipment.operating_days_per_week or 7
    total = ZERO
    day = timezone.localtime(begin).date()
    last = timezone.localtime(finish).date()
    while day <= last:
        if day.weekday() < days:
            low, high = max(begin, _aware(day)), min(finish, _aware(day + timedelta(days=1)))
            if high > low:
                total += min(Decimal(str((high - low).total_seconds() / 3600)), cap)
        day += timedelta(days=1)
    return total


@dataclass
class Reliability:
    required: Decimal = ZERO
    downtime_all: Decimal = ZERO
    downtime_failure: Decimal = ZERO
    failures: int = 0
    failures_stopped: int = 0
    repair_hours: list = field(default_factory=list)
    equipment_count: int = 0

    @property
    def mtbf(self):
        return (self.required - self.downtime_failure) / self.failures if self.failures else None

    @property
    def mttr(self):
        return sum(self.repair_hours, ZERO) / len(self.repair_hours) if self.repair_hours else None

    @property
    def mean_stop(self):
        return self.downtime_failure / self.failures_stopped if self.failures_stopped else None

    @property
    def availability(self):
        return max(ZERO, (self.required - self.downtime_all) / self.required * 100) if self.required else None

    @property
    def intrinsic(self):
        return max(ZERO, (self.required - self.downtime_failure) / self.required * 100) if self.required else None

    def add(self, other):
        self.required += other.required
        self.downtime_all += other.downtime_all
        self.downtime_failure += other.downtime_failure
        self.failures += other.failures
        self.failures_stopped += other.failures_stopped
        self.repair_hours += other.repair_hours
        self.equipment_count += other.equipment_count


def scope(*, unit=None, family=None, equipment=None):
    """Équipements concernés (hors réformés), selon les filtres unité, famille de premier niveau, équipement."""
    items = Equipment.objects.exclude(status=Equipment.Status.RETIRED)
    if equipment is not None:
        items = items.filter(pk=equipment.pk)
    items = list(items.only("pk", "code", "designation", "location_id", "family_id", "required_hours_per_day",
                            "operating_days_per_week"))
    if unit is not None:
        units = finance.location_units()
        items = [e for e in items if (units.get(e.location_id) or None) and units[e.location_id].pk == unit.pk]
    if family is not None:
        roots = finance.family_roots()
        items = [e for e in items if roots.get(e.family_id) and roots[e.family_id].pk == family.pk]
    return items


def failures(equipment_ids, start, end):
    low, high = _aware(start), _aware(end + timedelta(days=1))
    return (WorkOrder.objects.filter(kind=WorkOrder.Kind.CORRECTIVE, status__in=DONE, equipment_id__in=equipment_ids)
            .filter(Q(started_at__gte=low, started_at__lt=high) | Q(started_at__isnull=True, created_at__gte=low, created_at__lt=high)))


def reliability_by_equipment(equipment_list, start, end):
    """{id d'équipement: Reliability} sur la période."""
    now = timezone.now()
    ids = [e.pk for e in equipment_list]
    result = {e.pk: Reliability(required=required_hours(e, start, min(end, timezone.localdate())), equipment_count=1)
              for e in equipment_list}
    by_id = {e.pk: e for e in equipment_list}
    events = Downtime.objects.filter(
        equipment_id__in=ids, production_stopped=True, started_at__lt=_aware(end + timedelta(days=1)),
    ).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=_aware(start)))
    for event in events:
        hours = downtime_hours(event, by_id[event.equipment_id], start, end, now)
        rel = result[event.equipment_id]
        rel.downtime_all += hours
        if event.origin == Downtime.Origin.FAILURE:
            rel.downtime_failure += hours
    for wo in failures(ids, start, end):
        rel = result[wo.equipment_id]
        rel.failures += 1
        if wo.production_stopped:
            rel.failures_stopped += 1
        if wo.started_at and wo.finished_at and wo.finished_at > wo.started_at:
            rel.repair_hours.append(Decimal(str((wo.finished_at - wo.started_at).total_seconds() / 3600)))
    return result


def reliability(equipment_list, start, end):
    total = Reliability()
    for rel in reliability_by_equipment(equipment_list, start, end).values():
        total.add(rel)
    return total


def closed_orders(equipment_ids, start, end, kind=""):
    orders = WorkOrder.objects.filter(status__in=DONE, equipment_id__in=equipment_ids,
                                      finished_at__gte=_aware(start), finished_at__lt=_aware(end + timedelta(days=1)))
    return orders.filter(kind=kind) if kind else orders


def preventive_compliance(equipment_ids, start, end):
    from django.db.models.functions import Coalesce

    due = (WorkOrder.objects.filter(kind=WorkOrder.Kind.PREVENTIVE, equipment_id__in=equipment_ids)
           .annotate(reference_due=Coalesce("original_due_date", "due_date"))
           .filter(reference_due__gte=start, reference_due__lte=min(end, timezone.localdate())))
    total = realized = on_time = 0
    for wo in due.only("status", "finished_at", "original_due_date", "due_date"):
        total += 1
        if wo.status in DONE:
            realized += 1
            reference = wo.original_due_date or wo.due_date
            if wo.finished_at and timezone.localtime(wo.finished_at).date() <= reference:
                on_time += 1
    return {"due": total, "realized": realized, "on_time": on_time,
            "realization_rate": Decimal(realized * 100) / total if total else None,
            "on_time_rate": Decimal(on_time * 100) / total if total else None}


def parts_consumption(equipment_ids, start, end):
    from apps.inventory.models import StockMovement

    movements = StockMovement.objects.filter(
        kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN], moved_at__gte=_aware(start),
        moved_at__lt=_aware(end + timedelta(days=1)),
    ).filter(Q(equipment_id__in=equipment_ids) | Q(work_order__equipment_id__in=equipment_ids))
    return -(movements.aggregate(v=Sum("value"))["v"] or ZERO)


def month_ranges(end, count=12):
    """Les `count` derniers mois civils jusqu'au mois de `end` inclus : [(début, fin, libellé)]."""
    ranges, year, month = [], end.year, end.month
    for _i in range(count):
        first = date(year, month, 1)
        last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        ranges.append((first, min(last, end), finance.month_label(year, month)))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(ranges))


def compute(*, start, end, unit=None, family=None, equipment=None, kind=""):
    """Tous les indicateurs de la page, pour la période et les filtres."""
    items = scope(unit=unit, family=family, equipment=equipment)
    ids = [e.pk for e in items]
    per_equipment = reliability_by_equipment(items, start, end)
    total = Reliability()
    for rel in per_equipment.values():
        total.add(rel)
    closed = list(closed_orders(ids, start, end).only("pk", "kind", "equipment_id"))
    hours = {row["work_order_id"]: row["h"] for row in TimeEntry.objects.filter(work_order_id__in=[o.pk for o in closed])
             .values("work_order_id").annotate(h=Sum("hours"))}
    by_kind = Counter(o.kind for o in closed)
    hours_by_kind = Counter()
    for order in closed:
        hours_by_kind[order.kind] += hours.get(order.pk, ZERO) or ZERO
    total_hours = sum(hours_by_kind.values(), ZERO)
    open_orders = WorkOrder.objects.filter(status__in=WorkOrder.OPEN_STATUSES, equipment_id__in=ids)
    backlog = open_orders.aggregate(h=Sum("estimated_hours"))["h"] or ZERO
    costs = finance.cost_records(start, end, unit=unit, family=family, equipment=equipment, kind=kind)
    cost_by_equipment = Counter()
    for record in costs:
        cost_by_equipment[record.equipment_id] += record.total
    names = {e.pk: e for e in items}
    table = []
    for pk, rel in per_equipment.items():
        table.append({"equipment": names[pk], "rel": rel, "cost": cost_by_equipment.get(pk, ZERO)})
    from apps.inventory.selectors import stock_value

    units = finance.location_units()
    location_of = {e.pk: e.location_id for e in items}
    by_unit = Counter()
    for order in closed:
        unit_obj = units.get(location_of.get(order.equipment_id))
        by_unit[unit_obj.name if unit_obj else str(_("Hors unité"))] += 1
    return {
        "equipment_count": len(items), "rel": total,
        "preventive": preventive_compliance(ids, start, end),
        "closed_count": len(closed), "by_kind": by_kind, "hours_by_kind": hours_by_kind, "total_hours": total_hours,
        "corrective_rate": Decimal(by_kind.get(WorkOrder.Kind.CORRECTIVE, 0) * 100) / len(closed) if closed else None,
        "corrective_hours_rate": hours_by_kind.get(WorkOrder.Kind.CORRECTIVE, ZERO) * 100 / total_hours if total_hours else None,
        "backlog_hours": backlog, "backlog_days": backlog / 8,
        "late": open_orders.filter(due_date__lt=timezone.localdate()).count(),
        "parts": parts_consumption(ids, start, end), "stock_value": stock_value(),
        "cost": finance.totals(costs)["total"],
        "top_failures": sorted((row for row in table if row["rel"].failures), key=lambda r: (-r["rel"].failures, -r["rel"].downtime_failure))[:10],
        "top_costs": sorted((row for row in table if row["cost"]), key=lambda r: -r["cost"])[:10],
        "table": sorted(table, key=lambda r: (-r["rel"].failures, -r["cost"], r["equipment"].code)),
        "by_unit": OrderedDict(sorted(by_unit.items(), key=lambda kv: -kv[1])),
    }


def trend(*, end, unit=None, family=None, equipment=None, months=12):
    """Évolution mensuelle : pannes, MTBF, MTTR, disponibilité, coût."""
    items = scope(unit=unit, family=family, equipment=equipment)
    rows = []
    for first, last, label in month_ranges(end, months):
        rel = reliability(items, first, last)
        rows.append({
            "label": label, "failures": rel.failures,
            "mtbf": float(rel.mtbf) if rel.mtbf is not None else None,
            "mttr": float(rel.mttr) if rel.mttr is not None else None,
            "availability": float(rel.availability) if rel.availability is not None else None,
            "cost": float(finance.totals(finance.cost_records(first, last, unit=unit, family=family, equipment=equipment))["total"]),
        })
    return rows
