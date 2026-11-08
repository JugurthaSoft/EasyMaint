"""Branchements du préventif sur les autres modules (sans que ceux-ci le connaissent)."""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.assets.models import MeterReading
from apps.core.tenancy import tenant_context
from apps.workorders.signals import work_order_closed

logger = logging.getLogger("easymaint")


@receiver(work_order_closed)
def recompute_plan_schedule(sender, work_order, outcome, **kwargs):
    from .services import on_work_order_closed

    on_work_order_closed(work_order, outcome)


@receiver(post_save, sender=MeterReading)
def generate_after_reading(sender, instance, created, **kwargs):
    """Un nouveau relevé peut atteindre un seuil : on vérifie les plans de ce compteur après l'enregistrement."""
    if not created:
        return
    tenant, meter_id = instance.tenant, instance.meter_id

    def run():
        from .models import PreventivePlan
        from .services import generate_due_work_orders

        try:
            with tenant_context(tenant):
                plans = PreventivePlan.objects.filter(is_active=True, meter_id=meter_id)
                generate_due_work_orders(plans=plans)
        except Exception:  # ne jamais faire échouer la saisie d'un relevé
            logger.exception("Vérification des plans après relevé impossible (compteur %s)", meter_id)

    transaction.on_commit(run)
