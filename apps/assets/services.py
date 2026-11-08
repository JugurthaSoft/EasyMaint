"""Écritures métier du patrimoine."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import AuditLog
from apps.core.services import log_action

from .models import Equipment, Meter, MeterReading


@transaction.atomic
def record_reading(meter, value, *, reading_at=None, user=None, source=MeterReading.Source.MANUAL, note=""):
    """
    Enregistre un relevé de compteur.

    Règles :
    - pas de relevé dans le futur (5 minutes de tolérance d'horloge) ;
    - valeur positive ;
    - compteur cumulatif : la valeur doit rester entre le relevé précédent et le suivant ;
    - la valeur actuelle du compteur suit toujours le relevé le plus récent.
    """
    reading_at = reading_at or timezone.now()
    value = Decimal(str(value))
    if reading_at > timezone.now() + timedelta(minutes=5):
        raise ValidationError(_("La date du relevé ne peut pas être dans le futur."))
    if value < 0:
        raise ValidationError(_("La valeur d'un compteur ne peut pas être négative."))

    meter = Meter.objects.select_for_update().get(pk=meter.pk)
    if meter.is_cumulative:
        previous = meter.readings.filter(reading_at__lte=reading_at).order_by("-reading_at").first()
        following = meter.readings.filter(reading_at__gt=reading_at).order_by("reading_at").first()
        if previous is not None and value < previous.value:
            raise ValidationError(
                _("Valeur inférieure au relevé du %(date)s (%(value)s). Un compteur cumulatif ne diminue pas.")
                % {"date": timezone.localtime(previous.reading_at).strftime("%d/%m/%Y %H:%M"), "value": previous.value}
            )
        if following is not None and value > following.value:
            raise ValidationError(
                _("Valeur supérieure au relevé suivant du %(date)s (%(value)s).")
                % {"date": timezone.localtime(following.reading_at).strftime("%d/%m/%Y %H:%M"), "value": following.value}
            )

    reading = MeterReading.objects.create(
        meter=meter, value=value, reading_at=reading_at, source=source, note=note, created_by=user,
    )
    if meter.last_reading_at is None or reading_at >= meter.last_reading_at:
        meter.current_value = value
        meter.last_reading_at = reading_at
        meter.save(update_fields=["current_value", "last_reading_at", "updated_at"])
    return reading


@transaction.atomic
def change_status(equipment, new_status, *, request=None):
    """Change l'état d'un équipement et le trace dans le journal."""
    if new_status not in Equipment.Status.values:
        raise ValidationError(_("État inconnu."))
    if equipment.status == new_status:
        return equipment
    before = equipment.get_status_display()
    equipment.status = new_status
    equipment.save(update_fields=["status", "updated_at"])
    log_action(
        AuditLog.Action.UPDATE, request=request, obj=equipment,
        changes={str(_("État")): [str(before), str(equipment.get_status_display())]},
    )
    return equipment
