"""
Rapport mensuel de maintenance.

    python manage.py generate_monthly_report                  # mois écoulé, toutes les entreprises (s'il manque)
    python manage.py generate_monthly_report --mois 2026-10   # un mois précis, refait s'il existe
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Tenant
from apps.core.tenancy import tenant_context
from apps.kpi.reports import generate, generate_missing_for_all_tenants


class Command(BaseCommand):
    help = "Produit le rapport mensuel de maintenance (PDF conservé dans l'application)."

    def add_arguments(self, parser):
        parser.add_argument("--mois", help="Mois au format AAAA-MM (par défaut : le mois écoulé, s'il manque)")

    def handle(self, *args, mois=None, **options):
        if not mois:
            created = generate_missing_for_all_tenants()
            self.stdout.write(self.style.SUCCESS(f"{created} rapport(s) produit(s)."))
            return
        try:
            year, month = (int(part) for part in mois.split("-"))
            assert 1 <= month <= 12
        except (ValueError, AssertionError):
            raise CommandError("Format attendu : AAAA-MM, par exemple 2026-10.") from None
        for tenant in Tenant.objects.filter(is_active=True):
            with tenant_context(tenant):
                generate(tenant, year, month)
        self.stdout.write(self.style.SUCCESS(f"Rapport {month:02d}/{year} produit."))
