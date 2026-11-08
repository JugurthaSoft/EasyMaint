"""
Règles du conditionnel.

- Le niveau d'une mesure se calcule avec le seuil en vigueur à sa date (à défaut, le
  plus ancien seuil défini pour ce point et ce paramètre ; sans seuil : « sans seuil »).
- Une mesure au moins « attention » ouvre une alerte, ou met à jour l'alerte déjà ouverte
  sur le même point et le même paramètre (jamais de doublon).
- Les règles de déclenchement actives créent, une seule fois par alerte, une demande
  d'intervention ou un OT conditionnel quand les N dernières mesures atteignent leur niveau.

Les droits sont contrôlés dans les vues ; ces fonctions sont aussi appelées par le
système (démonstration, imports).
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.formatting import smart_number
from apps.core.models import AuditLog
from apps.core.services import log_action
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder

from .models import (
    LEVEL_RANK,
    Alert,
    Level,
    Measurement,
    MeasurementSession,
    Threshold,
    TriggerRule,
)


def threshold_for(point, parameter, at_date):
    """Seuil applicable à une date : le plus récent déjà en vigueur, sinon le plus ancien défini."""
    thresholds = Threshold.objects.filter(point=point, parameter=parameter)
    current = thresholds.filter(valid_from__lte=at_date).order_by("-valid_from", "-pk").first()
    return current or thresholds.order_by("valid_from", "pk").first()


def evaluate(point, parameter, value, measured_at):
    """(niveau, seuil utilisé) pour une valeur."""
    threshold = threshold_for(point, parameter, timezone.localtime(measured_at).date())
    if threshold is None:
        return Level.UNKNOWN, None
    return threshold.level_for(value), threshold


def parse_value(raw):
    """Valeur saisie (« 4,5 » ou « 4.5 ») → Decimal ; vide → None ; invalide → ValidationError."""
    text = (raw or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValidationError(_("« %(v)s » n'est pas un nombre.") % {"v": raw})


def threshold_label(threshold, level):
    if threshold is None:
        return ""
    high = getattr(threshold, f"{level}_high", None)
    low = getattr(threshold, f"{level}_low", None)
    parts = []
    if high is not None:
        parts.append(f"≥ {smart_number(high)}")
    if low is not None:
        parts.append(f"≤ {smart_number(low)}")
    return " ou ".join(parts)


@transaction.atomic
def record_session(*, equipment, kind, measured_at, values, user=None, technician=None, **header):
    """
    Enregistre une tournée (ou un prélèvement d'huile) et ses mesures, puis traite les alertes.
    `values` : liste de (point, paramètre, valeur Decimal).
    """
    if measured_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError(_("La date des mesures ne peut pas être dans le futur."))
    values = [(p, prm, v) for p, prm, v in values if v is not None]
    if not values:
        raise ValidationError(_("Saisissez au moins une valeur."))
    for point, parameter, _value in values:
        if point.equipment_id != equipment.pk:
            raise ValidationError(_("Le point %(p)s n'appartient pas à cet équipement.") % {"p": point.code})
        if not point.parameters.filter(pk=parameter.pk).exists():
            raise ValidationError(_("Le paramètre %(c)s n'est pas mesuré sur le point %(p)s.") % {"c": parameter.code, "p": point.code})
    session = MeasurementSession.objects.create(
        equipment=equipment, kind=kind, measured_at=measured_at, technician=technician, created_by=user, **header,
    )
    for point, parameter, value in values:
        level, threshold = evaluate(point, parameter, value, measured_at)
        measurement = Measurement.objects.create(
            session=session, point=point, parameter=parameter, value=value, level=level, threshold=threshold,
            measured_at=measured_at, created_by=user,
        )
        process_measurement(measurement, user=user)
    log_action(AuditLog.Action.CREATE, user=user, obj=session, username="système" if user is None else "",
               changes={_("Mesures"): ["", str(len(values))]})
    return session


def _later_measurement_exists(measurement):
    return Measurement.objects.filter(
        point=measurement.point, parameter=measurement.parameter, measured_at__gt=measurement.measured_at,
    ).exists()


def process_measurement(measurement, *, user=None):
    """Ouvre ou met à jour l'alerte du point/paramètre, puis applique les règles. Renvoie l'alerte ou None."""
    # Une mesure saisie après coup, plus ancienne que la dernière connue, ne change pas l'état actuel.
    if _later_measurement_exists(measurement):
        return None
    alert = (
        Alert.objects.filter(point=measurement.point, parameter=measurement.parameter)
        .exclude(status=Alert.Status.CLOSED).order_by("-opened_at").first()
    )
    rank = LEVEL_RANK.get(measurement.level, 0)
    if alert is None:
        if rank == 0:
            return None
        alert = Alert.objects.create(
            point=measurement.point, parameter=measurement.parameter, level=measurement.level, max_level=measurement.level,
            opened_at=measurement.measured_at, first_measurement=measurement, last_measurement=measurement, created_by=user,
        )
    else:
        alert.level = measurement.level if measurement.level != Level.UNKNOWN else alert.level
        if rank > LEVEL_RANK.get(alert.max_level, 0):
            alert.max_level = measurement.level
        alert.last_measurement = measurement
        alert.save()
    if rank > 0:
        apply_rules(alert, measurement)
    return alert


def _consecutive_reached(measurement, rule):
    recent = list(
        Measurement.objects.filter(point=measurement.point, parameter=measurement.parameter, measured_at__lte=measurement.measured_at)
        .order_by("-measured_at", "-pk").values_list("level", flat=True)[: rule.consecutive]
    )
    minimum = LEVEL_RANK[rule.min_level]
    return len(recent) == rule.consecutive and all(LEVEL_RANK.get(level, 0) >= minimum for level in recent)


def describe(measurement):
    unit = f" {measurement.parameter.unit}" if measurement.parameter.unit else ""
    return _("%(point)s — %(param)s : %(value)s%(unit)s (%(level)s, seuil %(threshold)s) le %(date)s") % {
        "point": measurement.point.name, "param": measurement.parameter.name, "value": smart_number(measurement.value),
        "unit": unit, "level": measurement.get_level_display().lower(),
        "threshold": threshold_label(measurement.threshold, measurement.level) or "—",
        "date": timezone.localtime(measurement.measured_at).strftime("%d/%m/%Y %H:%M"),
    }


def apply_rules(alert, measurement):
    """Applique la première règle satisfaite, si l'alerte n'a pas encore donné lieu à une demande ou un OT."""
    if alert.work_request_id or alert.work_order_id:
        return None
    rules = TriggerRule.objects.filter(is_active=True, parameter=measurement.parameter).filter(
        Q(equipment__isnull=True) | Q(equipment=measurement.point.equipment_id)
    )
    rank = LEVEL_RANK.get(measurement.level, 0)
    for rule in sorted(rules, key=lambda r: (-LEVEL_RANK[r.min_level], r.name)):
        if rank < LEVEL_RANK[rule.min_level] or not _consecutive_reached(measurement, rule):
            continue
        text = _("Alerte conditionnelle (règle « %(rule)s ») : %(detail)s") % {"rule": rule.name, "detail": describe(measurement)}
        equipment = measurement.point.equipment
        if rule.action == TriggerRule.Action.WORK_ORDER:
            alert.work_order = wo_services.create_work_order(
                user=None, equipment=equipment, kind=WorkOrder.Kind.CONDITIONAL, priority=rule.priority,
                title=(_("%(param)s en %(level)s — %(point)s") % {
                    "param": measurement.parameter.name, "level": measurement.get_level_display().lower(), "point": measurement.point.name,
                })[:200],
                description=text, automatic=True, origin=_("Créé par la règle « %(r)s »") % {"r": rule.name},
            )
        else:
            alert.work_request = wo_services.create_request(
                user=None, equipment=equipment, description=text, priority=rule.priority, production_stopped=False, automatic=True,
            )
        alert.rule = rule
        alert.save(update_fields=["work_order", "work_request", "rule", "updated_at"])
        return rule
    return None


@transaction.atomic
def acknowledge(alert, *, user, comment=""):
    if alert.status != Alert.Status.OPEN:
        raise ValidationError(_("Seule une alerte ouverte peut être acquittée."))
    alert.status = Alert.Status.ACKNOWLEDGED
    alert.acknowledged_by, alert.acknowledged_at = user, timezone.now()
    if comment.strip():
        alert.comment = comment.strip()[:255]
    alert.save()
    log_action(AuditLog.Action.UPDATE, user=user, obj=alert, changes={_("Alerte"): ["", _("acquittée")]})
    return alert


@transaction.atomic
def close(alert, *, user, comment):
    if alert.status == Alert.Status.CLOSED:
        raise ValidationError(_("Cette alerte est déjà close."))
    if not comment.strip():
        raise ValidationError(_("Indiquez comment l'alerte a été traitée."))
    alert.status = Alert.Status.CLOSED
    alert.closed_by, alert.closed_at = user, timezone.now()
    alert.comment = comment.strip()[:255]
    alert.save()
    log_action(AuditLog.Action.UPDATE, user=user, obj=alert, changes={_("Alerte"): ["", _("close : %(c)s") % {"c": alert.comment}]})
    return alert


@transaction.atomic
def create_work_order_from_alert(alert, *, user):
    """Bouton « Créer un OT » d'une alerte (droits vérifiés par le service des OT)."""
    if alert.work_order_id:
        raise ValidationError(_("Un OT existe déjà pour cette alerte."))
    measurement = alert.last_measurement
    detail = describe(measurement) if measurement else str(alert)
    alert.work_order = wo_services.create_work_order(
        user=user, equipment=alert.point.equipment, kind=WorkOrder.Kind.CONDITIONAL,
        priority=2 if LEVEL_RANK.get(alert.level, 0) >= 2 else 3,
        title=(_("%(param)s en %(level)s — %(point)s") % {
            "param": alert.parameter.name, "level": alert.get_level_display().lower(), "point": alert.point.name,
        })[:200],
        description=_("Alerte conditionnelle : %(d)s") % {"d": detail}, origin=_("Créé depuis une alerte conditionnelle"),
    )
    if alert.status == Alert.Status.OPEN:
        alert.status = Alert.Status.ACKNOWLEDGED
        alert.acknowledged_by, alert.acknowledged_at = user, timezone.now()
    alert.save()
    return alert.work_order


@transaction.atomic
def create_request_from_alert(alert, *, user):
    if alert.work_request_id or alert.work_order_id:
        raise ValidationError(_("Une demande ou un OT existe déjà pour cette alerte."))
    measurement = alert.last_measurement
    detail = describe(measurement) if measurement else str(alert)
    alert.work_request = wo_services.create_request(
        user=user, equipment=alert.point.equipment, description=_("Alerte conditionnelle : %(d)s") % {"d": detail},
        priority=2 if LEVEL_RANK.get(alert.level, 0) >= 2 else 3, production_stopped=False,
    )
    alert.save(update_fields=["work_request", "updated_at"])
    return alert.work_request


def chart_series(point, parameter, limit=60):
    """Données d'une courbe : dates, valeurs et seuils en vigueur à chaque date."""
    measurements = list(
        Measurement.objects.filter(point=point, parameter=parameter).order_by("-measured_at", "-pk")[:limit]
    )[::-1]
    thresholds = list(Threshold.objects.filter(point=point, parameter=parameter).order_by("valid_from", "pk"))

    def applicable(day):
        current = None
        for threshold in thresholds:
            if threshold.valid_from <= day:
                current = threshold
        return current or (thresholds[0] if thresholds else None)

    def number(value):
        return float(value) if value is not None else None

    series = {"labels": [], "values": [], "levels": []}
    for key in ("warning_high", "alarm_high", "critical_high", "warning_low", "alarm_low", "critical_low"):
        series[key] = []
    for m in measurements:
        local = timezone.localtime(m.measured_at)
        series["labels"].append(local.strftime("%d/%m/%y"))
        series["values"].append(float(m.value))
        series["levels"].append(m.level)
        threshold = applicable(local.date())
        for key in ("warning_high", "alarm_high", "critical_high", "warning_low", "alarm_low", "critical_low"):
            series[key].append(number(getattr(threshold, key)) if threshold else None)
    # Courbes de seuils vides retirées (un paramètre sans seuil bas n'affiche que les seuils hauts)
    for key in ("warning_high", "alarm_high", "critical_high", "warning_low", "alarm_low", "critical_low"):
        if all(v is None for v in series[key]):
            series[key] = []
    series["unit"] = parameter.unit
    return series
