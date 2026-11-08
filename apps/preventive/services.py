"""
Règles du préventif : échéances, génération des OT, recalcul après réalisation.

Règles :
- un plan n'a jamais deux OT en attente : tant qu'un OT du plan n'est ni validé
  ni annulé, aucun nouvel OT n'est créé ;
- calendrier : l'OT est créé quand aujourd'hui ≥ échéance − anticipation ;
- compteur : l'OT est créé quand valeur ≥ dernier entretien + intervalle − anticipation ;
- les deux : le premier des deux seuils atteint déclenche l'OT ;
- à la validation de l'OT, l'échéance suivante est recalculée (périodicité fixe :
  à partir de l'échéance d'origine ; glissante : à partir de la date de réalisation) ;
- à l'annulation, l'échéance est sautée (le plan passe à la suivante).
"""
import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.formatting import smart_number
from apps.core.models import AuditLog
from apps.core.services import log_action, next_document_number
from apps.inventory.services import reserve_plan_parts
from apps.workorders.models import ChecklistItem, StatusLog, WorkOrder

from .models import PreventivePlan

logger = logging.getLogger("easymaint")

CLOSED_STATUSES = (WorkOrder.Status.VALIDATED, WorkOrder.Status.CANCELLED)


def add_period(start, value, unit):
    """Ajoute `value` jours, semaines, mois ou années. 31/01 + 1 mois = 28/02 (ou 29/02)."""
    value = int(value or 0)
    if unit == PreventivePlan.PeriodUnit.DAY:
        return start + timedelta(days=value)
    if unit == PreventivePlan.PeriodUnit.WEEK:
        return start + timedelta(weeks=value)
    months = value * 12 if unit == PreventivePlan.PeriodUnit.YEAR else value
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def next_after(base, plan, limit):
    """Première échéance strictement postérieure à `limit`, en partant de `base` (base + 1 période au minimum)."""
    due = add_period(base, plan.period_value, plan.period_unit)
    guard = 0
    while due <= limit and guard < 1000:
        due = add_period(due, plan.period_value, plan.period_unit)
        guard += 1
    return due


def pending_work_order(plan):
    """OT du plan pas encore validé ni annulé (il ne peut y en avoir qu'un)."""
    return plan.work_orders.exclude(status__in=CLOSED_STATUSES).order_by("-created_at").first()


def meter_daily_rate(meter, today=None, days=30):
    """Utilisation moyenne par jour sur les `days` derniers jours de relevés, ou None."""
    today = today or timezone.localdate()
    readings = list(meter.readings.order_by("reading_at").values_list("reading_at", "value"))
    if len(readings) < 2:
        return None
    since = timezone.now() - timedelta(days=days)
    recent = [r for r in readings if r[0] >= since]
    window = recent if len(recent) >= 2 else readings[-2:]
    (first_at, first_value), (last_at, last_value) = window[0], window[-1]
    elapsed = (last_at - first_at).total_seconds() / 86400
    if elapsed <= 0 or last_value <= first_value:
        return None
    return (Decimal(last_value) - Decimal(first_value)) / Decimal(str(elapsed))


def estimated_meter_date(plan, today=None):
    """Date estimée à laquelle le compteur atteindra le seuil du plan, ou None si l'usage est inconnu."""
    today = today or timezone.localdate()
    threshold = plan.next_meter_threshold
    if threshold is None or plan.meter is None:
        return None
    remaining = threshold - plan.meter.current_value
    if remaining <= 0:
        return today
    rate = meter_daily_rate(plan.meter, today)
    if not rate:
        return None
    return today + timedelta(days=int((remaining / rate).to_integral_value()))


def due_status(plan, today=None):
    """
    (doit être généré ?, échéance de l'OT, motif). L'échéance est la date de l'OT à créer.
    """
    today = today or timezone.localdate()
    reasons, candidates, due = [], [], False
    if plan.uses_calendar and plan.next_due_date:
        candidates.append(plan.next_due_date)
        if today >= plan.next_due_date - timedelta(days=plan.lead_days):
            due = True
            reasons.append(_("échéance du %(d)s") % {"d": plan.next_due_date.strftime("%d/%m/%Y")})
    if plan.uses_meter and plan.meter_id and plan.next_meter_threshold is not None:
        threshold = plan.next_meter_threshold
        estimate = estimated_meter_date(plan, today)
        if plan.meter.current_value >= threshold - (plan.meter_lead or Decimal("0")):
            due = True
            reasons.append(_("compteur à %(v)s %(u)s (seuil %(s)s)") % {
                "v": smart_number(plan.meter.current_value), "u": plan.meter.unit, "s": smart_number(threshold),
            })
            candidates.append(estimate or today)
        elif estimate:
            candidates.append(estimate)
    due_date = min(candidates) if candidates else today
    # L'échéance de l'OT est la plus proche des deux (une échéance dépassée reste dépassée : l'OT apparaît en retard).
    return due, due_date, " ; ".join(str(r) for r in reasons)


def _create_from_plan(plan, *, due_date, reason, user=None):
    """Crée l'OT préventif du plan : intervenants, check-list, échéance d'origine."""
    technicians = list(plan.technicians.filter(is_active=True))
    someone = bool(technicians or plan.team_id)
    description = plan.operations
    if plan.instructions:
        description += "\n\n" + _("Instructions") + " :\n" + plan.instructions
    work_order = WorkOrder.objects.create(
        number=next_document_number("OT"), kind=WorkOrder.Kind.PREVENTIVE, equipment=plan.equipment,
        title=plan.name[:200], description=description, priority=plan.priority,
        planned_date=due_date, due_date=due_date, original_due_date=due_date,
        estimated_hours=plan.estimated_hours, team=plan.team, preventive_plan=plan,
        status=WorkOrder.Status.ASSIGNED if someone else WorkOrder.Status.TO_PLAN, created_by=user,
    )
    if technicians:
        work_order.technicians.set(technicians)
    for item in plan.checklist.all():
        ChecklistItem.objects.create(work_order=work_order, label=item.label, position=item.position, created_by=user)
    reserve_plan_parts(work_order, plan, user=user)
    comment = _("Généré par le plan %(code)s (%(reason)s)") % {"code": plan.code, "reason": reason}
    StatusLog.objects.create(work_order=work_order, to_status=work_order.status, user=user, comment=comment[:255])
    log_action(AuditLog.Action.CREATE, user=user, obj=work_order, username="" if user else "système",
               changes={_("Origine"): ["", comment]})
    return work_order


@transaction.atomic
def generate_for_plan(plan, *, today=None, force=False, user=None):
    """
    Génère l'OT du plan s'il est dû (ou immédiatement si `force`). Renvoie l'OT créé ou None.
    `force` sert au bouton « Générer maintenant » : il ignore l'anticipation, jamais la règle d'unicité.
    """
    plan = PreventivePlan.objects.select_for_update(of=("self",)).select_related("meter", "equipment").get(pk=plan.pk)
    if not plan.is_active or pending_work_order(plan) is not None:
        return None
    today = today or timezone.localdate()
    due, due_date, reason = due_status(plan, today)
    if not due and not force:
        return None
    if not due:
        reason = _("génération manuelle")
    return _create_from_plan(plan, due_date=due_date, reason=reason, user=user)


def generate_now(plan, *, user):
    """Bouton « Générer l'OT maintenant » de la fiche plan."""
    if not user.has_capability("preventive.manage"):
        raise PermissionDenied
    if not plan.is_active:
        raise ValidationError(_("Ce plan est désactivé."))
    if pending_work_order(plan) is not None:
        raise ValidationError(_("Un OT de ce plan est déjà en cours : il doit être validé ou annulé avant le suivant."))
    return generate_for_plan(plan, force=True, user=user)


def generate_due_work_orders(*, today=None, plans=None):
    """Parcourt les plans actifs de l'entreprise courante et crée les OT dus. Renvoie la liste créée."""
    today = today or timezone.localdate()
    queryset = plans if plans is not None else PreventivePlan.objects.filter(is_active=True)
    created = []
    for plan in queryset.select_related("equipment"):
        if plan.equipment.status == plan.equipment.Status.RETIRED:
            continue
        try:
            work_order = generate_for_plan(plan, today=today)
        except Exception:  # un plan mal paramétré ne doit pas bloquer les autres
            logger.exception("Génération impossible pour le plan %s", plan.pk)
            continue
        if work_order is not None:
            created.append(work_order)
    return created


@transaction.atomic
def on_work_order_closed(work_order, outcome):
    """Recalcule l'échéance du plan quand son OT est validé (réalisé) ou annulé (échéance sautée)."""
    if work_order.preventive_plan_id is None:
        return
    plan = PreventivePlan.objects.select_for_update(of=("self",)).select_related("meter").get(pk=work_order.preventive_plan_id)
    today = timezone.localdate()
    planned_due = work_order.original_due_date or work_order.due_date or plan.next_due_date or today
    if outcome == "validated":
        done_date = timezone.localtime(work_order.finished_at).date() if work_order.finished_at else today
        plan.last_done_date = done_date
        if plan.uses_calendar and plan.period_value:
            if plan.schedule_basis == PreventivePlan.Basis.FLOATING:
                plan.next_due_date = add_period(done_date, plan.period_value, plan.period_unit)
            else:
                plan.next_due_date = next_after(planned_due, plan, done_date)
    elif outcome == "cancelled":
        if plan.uses_calendar and plan.period_value:
            plan.next_due_date = next_after(planned_due, plan, today)
    else:
        return
    if plan.uses_meter and plan.meter is not None:
        plan.last_done_meter = plan.meter.current_value
    plan.save()


def projected_dates(plan, start, end):
    """Échéances calendaires prévues entre deux dates (pour le planning), hors OT déjà généré."""
    if not plan.is_active or not plan.uses_calendar or not plan.period_value or not plan.next_due_date:
        return []
    dates, current, guard = [], plan.next_due_date, 0
    if pending_work_order(plan) is not None:
        current = add_period(current, plan.period_value, plan.period_unit)
    while current <= end and guard < 400:
        if current >= start:
            dates.append(current)
        current = add_period(current, plan.period_value, plan.period_unit)
        guard += 1
    return dates
