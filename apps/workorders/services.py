"""
Cycle de vie des demandes et des ordres de travail.

Toute écriture métier passe par ces fonctions : elles vérifient les droits et
les transitions autorisées, tiennent à jour l'historique des statuts, les
pointages, les arrêts machine, l'état de l'équipement et les coûts.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.assets.models import Equipment
from apps.core.models import AuditLog
from apps.core.services import form_changes, log_action, next_document_number
from apps.workforce.models import technician_for

from .models import Downtime, StatusLog, TimeEntry, WorkOrder, WorkRequest
from .signals import work_order_closed

S = WorkOrder.Status

# Transitions autorisées : action -> (statuts de départ, statut d'arrivée)
TRANSITIONS = {
    "start": ((S.TO_PLAN, S.ASSIGNED), S.IN_PROGRESS),
    "wait_parts": ((S.IN_PROGRESS, S.WAITING_EXTERNAL), S.WAITING_PARTS),
    "wait_external": ((S.IN_PROGRESS, S.WAITING_PARTS), S.WAITING_EXTERNAL),
    "resume": ((S.WAITING_PARTS, S.WAITING_EXTERNAL), S.IN_PROGRESS),
    "finish": ((S.IN_PROGRESS, S.WAITING_PARTS, S.WAITING_EXTERNAL), S.DONE),
    "validate": ((S.DONE,), S.VALIDATED),
    "reopen": ((S.DONE,), S.IN_PROGRESS),
    "cancel": ((S.TO_PLAN, S.ASSIGNED, S.IN_PROGRESS, S.WAITING_PARTS, S.WAITING_EXTERNAL), S.CANCELLED),
}


def _now():
    return timezone.now()


def _require(user, capability):
    if not user.has_capability(capability):
        raise PermissionDenied


def _can_execute(user, work_order):
    """Le responsable (workorders.manage) peut tout exécuter ; un technicien, seulement ses OT."""
    if user.has_capability("workorders.manage"):
        return True
    if not user.has_capability("workorders.execute"):
        return False
    technician = technician_for(user)
    return technician is not None and work_order.technicians.filter(pk=technician.pk).exists()


def _set_status(work_order, new_status, user, comment=""):
    old = work_order.status
    work_order.status = new_status
    work_order.save()
    StatusLog.objects.create(work_order=work_order, from_status=old, to_status=new_status, user=user, comment=comment[:255])
    log_action(AuditLog.Action.UPDATE, user=user, obj=work_order, changes=_status_changes(old, new_status, comment))


def _status_changes(old, new, comment):
    changes = {_("Statut"): [str(S(old).label) if old in S.values else "", str(S(new).label)]}
    if comment:
        changes[_("Commentaire")] = ["", comment]
    return changes


def _check_transition(work_order, action):
    allowed_from, _target = TRANSITIONS[action]
    if work_order.status not in allowed_from:
        raise ValidationError(
            _("Action impossible : l'OT est « %(status)s ».") % {"status": work_order.get_status_display()}
        )


def _open_downtime(equipment, *, started_at, work_order=None, work_request=None, origin=Downtime.Origin.FAILURE):
    """Ouvre un arrêt (un seul arrêt ouvert par équipement et par OT/DI) et passe l'équipement en panne."""
    downtime = Downtime.objects.create(
        equipment=equipment, work_order=work_order, work_request=work_request, started_at=started_at, origin=origin,
    )
    if origin == Downtime.Origin.FAILURE and equipment.status == Equipment.Status.IN_SERVICE:
        equipment.status = Equipment.Status.BROKEN
        equipment.save(update_fields=["status", "updated_at"])
    return downtime


def _close_downtimes(queryset, ended_at):
    """Ferme les arrêts ouverts et remet l'équipement en service s'il n'a plus d'arrêt ouvert."""
    equipment_ids = set()
    for downtime in queryset.filter(ended_at__isnull=True):
        downtime.ended_at = max(ended_at, downtime.started_at)
        downtime.save(update_fields=["ended_at", "updated_at"])
        equipment_ids.add(downtime.equipment_id)
    for equipment in Equipment.objects.filter(pk__in=equipment_ids, status=Equipment.Status.BROKEN):
        if not Downtime.objects.filter(equipment=equipment, ended_at__isnull=True).exists():
            equipment.status = Equipment.Status.IN_SERVICE
            equipment.save(update_fields=["status", "updated_at"])


def _hours_between(start, end):
    seconds = max((end - start).total_seconds(), 0)
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Demandes d'intervention ---------------------------------------------------------

@transaction.atomic
def create_request(*, user, equipment, description, priority, production_stopped, automatic=False):
    """`automatic=True` : demande créée par le système (règle conditionnelle) ; `user` peut alors être None."""
    if not automatic:
        _require(user, "requests.create")
    request_obj = WorkRequest.objects.create(
        number=next_document_number("DI"), equipment=equipment, description=description, priority=priority,
        production_stopped=production_stopped, requested_by=user, requested_at=_now(), created_by=user,
    )
    if production_stopped:
        _open_downtime(equipment, started_at=request_obj.requested_at, work_request=request_obj)
    log_action(AuditLog.Action.CREATE, user=user, obj=request_obj, username="système" if user is None else "")
    return request_obj


@transaction.atomic
def accept_request(request_obj, *, user, kind=WorkOrder.Kind.CORRECTIVE, priority=None, note=""):
    """Accepte la DI : crée l'OT correspondant (statut « À planifier ») et lui rattache l'arrêt éventuel."""
    _require(user, "requests.manage")
    if request_obj.status != WorkRequest.Status.NEW:
        raise ValidationError(_("Cette demande a déjà été traitée."))
    work_order = WorkOrder.objects.create(
        number=next_document_number("OT"), kind=kind, equipment=request_obj.equipment,
        title=request_obj.description.strip().splitlines()[0][:200] if request_obj.description.strip() else request_obj.equipment.designation,
        description=request_obj.description, priority=priority or request_obj.priority,
        production_stopped=request_obj.production_stopped, status=S.TO_PLAN,
        due_date=timezone.localdate() if (priority or request_obj.priority) <= 2 else None,
        created_by=user,
    )
    StatusLog.objects.create(work_order=work_order, to_status=S.TO_PLAN, user=user, comment=_("Créé depuis %(n)s") % {"n": request_obj.number})
    Downtime.objects.filter(work_request=request_obj, work_order__isnull=True).update(work_order=work_order)
    request_obj.status = WorkRequest.Status.ACCEPTED
    request_obj.decided_by, request_obj.decided_at, request_obj.decision_note = user, _now(), note[:255]
    request_obj.work_order = work_order
    request_obj.save()
    log_action(AuditLog.Action.CREATE, user=user, obj=work_order, changes={_("Origine"): ["", request_obj.number]})
    return work_order


@transaction.atomic
def reject_request(request_obj, *, user, note):
    _require(user, "requests.manage")
    if request_obj.status != WorkRequest.Status.NEW:
        raise ValidationError(_("Cette demande a déjà été traitée."))
    if not note.strip():
        raise ValidationError(_("Indiquez le motif du refus."))
    request_obj.status = WorkRequest.Status.REJECTED
    request_obj.decided_by, request_obj.decided_at, request_obj.decision_note = user, _now(), note[:255]
    request_obj.save()
    _close_downtimes(Downtime.objects.filter(work_request=request_obj), _now())
    log_action(AuditLog.Action.UPDATE, user=user, obj=request_obj, changes={_("Décision"): ["", _("refusée : %(n)s") % {"n": note}]})
    return request_obj


# --- Ordres de travail ---------------------------------------------------------------

@transaction.atomic
def create_work_order(*, user, equipment, title, kind, priority, description="", production_stopped=False,
                      planned_date=None, due_date=None, estimated_hours=None, technicians=(), team=None, contractor=None,
                      automatic=False, origin=""):
    """
    Création directe d'un OT (sans demande), réservée aux rôles autorisés.
    `automatic=True` : OT créé par le système (règle conditionnelle) ; `user` peut alors être None.
    """
    if not automatic and not (user.has_capability("workorders.manage") or user.has_capability("workorders.create_direct")):
        raise PermissionDenied
    technicians = list(technicians)
    if not automatic and not technicians and not user.has_capability("workorders.manage"):
        # Un technicien qui crée un OT urgent se l'affecte à lui-même.
        own = technician_for(user)
        if own is not None:
            technicians = [own]
    status = S.ASSIGNED if (technicians or team or contractor) else S.TO_PLAN
    work_order = WorkOrder.objects.create(
        number=next_document_number("OT"), kind=kind, equipment=equipment, title=title, description=description,
        priority=priority, production_stopped=production_stopped, planned_date=planned_date, due_date=due_date,
        estimated_hours=estimated_hours, team=team, contractor=contractor, status=status, created_by=user,
    )
    if technicians:
        work_order.technicians.set(technicians)
    StatusLog.objects.create(work_order=work_order, to_status=status, user=user, comment=(origin or _("Création directe"))[:255])
    if production_stopped:
        _open_downtime(equipment, started_at=_now(), work_order=work_order)
    log_action(AuditLog.Action.CREATE, user=user, obj=work_order, username="système" if user is None else "")
    return work_order


@transaction.atomic
def plan_work_order(work_order, *, user, form):
    """Enregistre la planification (dates, équipe, techniciens) ; « À planifier » devient « Affecté » si quelqu'un est désigné."""
    _require(user, "workorders.manage")
    if not work_order.is_open:
        raise ValidationError(_("Un OT terminé, validé ou annulé ne se replanifie pas."))
    changes = form_changes(form)
    work_order = form.save()
    if changes:
        log_action(AuditLog.Action.UPDATE, user=user, obj=work_order, changes=changes)
    someone = work_order.technicians.exists() or work_order.team_id or work_order.contractor_id
    if work_order.status == S.TO_PLAN and someone:
        _set_status(work_order, S.ASSIGNED, user)
    elif work_order.status == S.ASSIGNED and not someone:
        _set_status(work_order, S.TO_PLAN, user, _("Plus aucun intervenant"))
    return work_order


def _running_entry(work_order, technician):
    return TimeEntry.objects.filter(work_order=work_order, technician=technician, ended_at__isnull=True).first()


def _stop_entry(entry, at):
    entry.ended_at = max(at, entry.started_at)
    entry.hours = _hours_between(entry.started_at, entry.ended_at)
    entry.save(update_fields=["ended_at", "hours", "updated_at"])


def _stop_all_timers(work_order, at):
    for entry in TimeEntry.objects.filter(work_order=work_order, ended_at__isnull=True):
        _stop_entry(entry, at)


@transaction.atomic
def start_timer(work_order, *, user):
    """
    Démarre le chronomètre du technicien connecté. Au premier démarrage, l'OT passe « En cours ».
    Un technicien n'a qu'un chronomètre actif : celui d'un autre OT est arrêté automatiquement.
    """
    if not _can_execute(user, work_order):
        raise PermissionDenied
    technician = technician_for(user)
    if technician is None:
        raise ValidationError(_("Votre compte n'est relié à aucune fiche technicien : le temps ne peut pas être pointé."))
    if work_order.status in (S.TO_PLAN, S.ASSIGNED):
        if not work_order.technicians.filter(pk=technician.pk).exists():
            work_order.technicians.add(technician)
        work_order.started_at = work_order.started_at or _now()
        _set_status(work_order, S.IN_PROGRESS, user)
    elif work_order.status != S.IN_PROGRESS:
        raise ValidationError(_("Reprenez d'abord l'intervention (statut « %(s)s »).") % {"s": work_order.get_status_display()})
    if _running_entry(work_order, technician):
        return work_order
    now = _now()
    for other in TimeEntry.objects.filter(technician=technician, ended_at__isnull=True).exclude(work_order=work_order):
        _stop_entry(other, now)
    TimeEntry.objects.create(
        work_order=work_order, technician=technician, started_at=now, hourly_rate=technician.rate_for(False), created_by=user,
    )
    if work_order.production_stopped and not work_order.downtimes.exists():
        _open_downtime(work_order.equipment, started_at=now, work_order=work_order)
    return work_order


@transaction.atomic
def stop_timer(work_order, *, user):
    technician = technician_for(user)
    entry = _running_entry(work_order, technician) if technician else None
    if entry is None:
        raise ValidationError(_("Aucun chronomètre en marche pour vous sur cet OT."))
    _stop_entry(entry, _now())
    return work_order


@transaction.atomic
def add_time_entry(work_order, *, user, technician, started_at, ended_at, is_overtime=False, note=""):
    """Saisie manuelle d'un temps (oubli de pointage, intervention de nuit...)."""
    if not (user.has_capability("workorders.manage") or (_can_execute(user, work_order) and technician_for(user) == technician)):
        raise PermissionDenied
    if work_order.status in (S.VALIDATED, S.CANCELLED):
        raise ValidationError(_("OT clôturé : temps non modifiable."))
    if ended_at <= started_at:
        raise ValidationError(_("La fin doit être postérieure au début."))
    if ended_at > _now() + timedelta(minutes=5):
        raise ValidationError(_("Le temps saisi ne peut pas être dans le futur."))
    entry = TimeEntry.objects.create(
        work_order=work_order, technician=technician, started_at=started_at, ended_at=ended_at,
        hours=_hours_between(started_at, ended_at), is_overtime=is_overtime,
        hourly_rate=technician.rate_for(is_overtime), note=note, created_by=user,
    )
    if not work_order.technicians.filter(pk=technician.pk).exists():
        work_order.technicians.add(technician)
    return entry


@transaction.atomic
def put_on_hold(work_order, *, user, action, reason):
    if not _can_execute(user, work_order):
        raise PermissionDenied
    _check_transition(work_order, action)
    if not reason.strip():
        raise ValidationError(_("Indiquez le motif de l'attente."))
    _stop_all_timers(work_order, _now())
    work_order.waiting_reason = reason[:255]
    _set_status(work_order, TRANSITIONS[action][1], user, reason)
    return work_order


@transaction.atomic
def resume(work_order, *, user):
    if not _can_execute(user, work_order):
        raise PermissionDenied
    _check_transition(work_order, "resume")
    work_order.waiting_reason = ""
    _set_status(work_order, S.IN_PROGRESS, user)
    return work_order


def finish_requirements(work_order):
    """Ce qui manque pour terminer l'OT (liste vide = l'OT peut être terminé)."""
    missing = []
    if not work_order.work_done.strip():
        missing.append(_("décrire les travaux réalisés"))
    if work_order.kind == WorkOrder.Kind.CORRECTIVE and not work_order.failure_cause_id:
        missing.append(_("indiquer la cause de la panne"))
    pending = work_order.checklist.filter(is_done=False).count()
    if pending:
        missing.append(_("compléter la check-list (%(n)s point(s) restant(s))") % {"n": pending})
    has_time = TimeEntry.objects.filter(work_order=work_order).filter(ended_at__isnull=True).exists() or (
        TimeEntry.objects.filter(work_order=work_order).aggregate(h=Sum("hours"))["h"] or 0
    ) > 0
    if not has_time and not work_order.contractor_id:
        missing.append(_("pointer le temps passé"))
    return missing


@transaction.atomic
def finish(work_order, *, user):
    if not _can_execute(user, work_order):
        raise PermissionDenied
    _check_transition(work_order, "finish")
    missing = finish_requirements(work_order)
    if missing:
        raise ValidationError(_("Avant de terminer : %(list)s.") % {"list": " ; ".join(str(m) for m in missing)})
    now = _now()
    _stop_all_timers(work_order, now)
    work_order.finished_at = now
    work_order.started_at = work_order.started_at or now
    _close_downtimes(work_order.downtimes.all(), now)
    _set_status(work_order, S.DONE, user)
    return work_order


# Fonctions (OT) -> montant ajoutées par les modules en aval : le magasin y inscrit la valeur
# des pièces délivrées, sans que ce module-ci ait à le connaître.
PARTS_COST_PROVIDERS = []


def compute_costs(work_order):
    """Coûts d'un OT calculés à partir des pointages, pièces (saisies et magasin) et dépenses."""
    labour = sum((entry.cost for entry in work_order.time_entries.all()), Decimal("0"))
    parts = sum((part.cost for part in work_order.parts.all()), Decimal("0"))
    parts += sum((provider(work_order) for provider in PARTS_COST_PROVIDERS), Decimal("0"))
    external = Decimal("0")
    other = Decimal("0")
    for expense in work_order.expenses.all():
        if expense.nature == expense.Nature.EXTERNAL:
            external += expense.amount
        else:
            other += expense.amount
    quantize = Decimal("0.001")
    result = {
        "labour": labour.quantize(quantize), "parts": parts.quantize(quantize),
        "external": external.quantize(quantize), "other": other.quantize(quantize),
    }
    result["total"] = sum(result.values(), Decimal("0"))
    return result


@transaction.atomic
def validate(work_order, *, user):
    """Validation par le responsable : les coûts sont figés, l'OT ne bouge plus."""
    _require(user, "workorders.validate")
    _check_transition(work_order, "validate")
    costs = compute_costs(work_order)
    work_order.labour_cost, work_order.parts_cost = costs["labour"], costs["parts"]
    work_order.external_cost, work_order.other_cost, work_order.total_cost = costs["external"], costs["other"], costs["total"]
    work_order.validated_by, work_order.validated_at = user, _now()
    _set_status(work_order, S.VALIDATED, user)
    work_order_closed.send(sender=WorkOrder, work_order=work_order, outcome="validated")
    return work_order


@transaction.atomic
def reopen(work_order, *, user, comment):
    """Refus de validation : l'OT retourne au technicien avec un commentaire."""
    _require(user, "workorders.validate")
    _check_transition(work_order, "reopen")
    if not comment.strip():
        raise ValidationError(_("Expliquez ce qui doit être repris."))
    work_order.finished_at = None
    _set_status(work_order, S.IN_PROGRESS, user, comment)
    return work_order


@transaction.atomic
def cancel(work_order, *, user, reason):
    _require(user, "workorders.manage")
    _check_transition(work_order, "cancel")
    if not reason.strip():
        raise ValidationError(_("Indiquez le motif d'annulation."))
    now = _now()
    _stop_all_timers(work_order, now)
    _close_downtimes(work_order.downtimes.all(), now)
    work_order.cancel_reason = reason[:255]
    _set_status(work_order, S.CANCELLED, user, reason)
    work_order_closed.send(sender=WorkOrder, work_order=work_order, outcome="cancelled")
    return work_order


@transaction.atomic
def postpone(work_order, *, user, new_date, reason):
    """
    Reporte un OT ouvert. L'échéance d'origine est conservée : le respect du planning
    se mesure toujours par rapport à elle.
    """
    _require(user, "workorders.manage")
    if not work_order.is_open:
        raise ValidationError(_("Seul un OT ouvert peut être reporté."))
    if new_date is None:
        raise ValidationError(_("Indiquez la nouvelle date."))
    if new_date < timezone.localdate():
        raise ValidationError(_("La nouvelle date ne peut pas être dans le passé."))
    if not reason.strip():
        raise ValidationError(_("Indiquez le motif du report."))
    old = work_order.due_date or work_order.planned_date
    if work_order.original_due_date is None:
        work_order.original_due_date = old
    work_order.planned_date = new_date
    work_order.due_date = new_date
    work_order.save()
    old_label = old.strftime("%d/%m/%Y") if old else "—"
    comment = _("Reporté du %(old)s au %(new)s : %(reason)s") % {
        "old": old_label, "new": new_date.strftime("%d/%m/%Y"), "reason": reason.strip(),
    }
    StatusLog.objects.create(
        work_order=work_order, from_status=work_order.status, to_status=work_order.status, user=user, comment=comment[:255],
    )
    log_action(
        AuditLog.Action.UPDATE, user=user, obj=work_order,
        changes={_("Échéance"): [old_label, new_date.strftime("%d/%m/%Y")], _("Motif du report"): ["", reason.strip()]},
    )
    return work_order


def ensure_editable(work_order, user):
    """Pièces, dépenses, check-list et compte rendu ne sont modifiables que sur un OT ouvert, par un intervenant autorisé."""
    if not work_order.is_open and work_order.status != S.DONE:
        raise ValidationError(_("OT clôturé : plus de modification possible."))
    if work_order.status == S.DONE and not user.has_capability("workorders.validate"):
        raise ValidationError(_("OT terminé : seul le valideur peut encore le corriger."))
    if not _can_execute(user, work_order):
        raise PermissionDenied
