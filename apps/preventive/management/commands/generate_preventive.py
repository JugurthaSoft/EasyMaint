"""
Crée les OT préventifs arrivés à échéance, pour toutes les entreprises actives.

    python manage.py generate_preventive
Lancée chaque nuit par le service « scheduler » ; peut aussi être lancée à la main.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant
from apps.core.tenancy import tenant_context
from apps.preventive.services import generate_due_work_orders


def run_for_all_tenants():
    """Renvoie {entreprise: nombre d'OT créés}."""
    results = {}
    for tenant in Tenant.objects.filter(is_active=True):
        with tenant_context(tenant):
            results[tenant] = len(generate_due_work_orders())
    return results


class Command(BaseCommand):
    help = "Génère les OT préventifs arrivés à échéance (toutes les entreprises)."

    def handle(self, *args, **options):
        results = run_for_all_tenants()
        total = sum(results.values())
        for tenant, count in results.items():
            if count:
                self.stdout.write(f"{tenant} : {count} OT préventif(s) créé(s)")
        self.stdout.write(self.style.SUCCESS(f"Terminé : {total} OT préventif(s) créé(s)."))
