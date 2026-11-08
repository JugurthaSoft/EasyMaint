"""
Tâches planifiées d'EasyMaint (service Docker « scheduler »).

    python manage.py run_scheduler

Génère les OT préventifs (et, s'il manque, le rapport mensuel du mois écoulé) au démarrage puis chaque jour à l'heure EASYMAINT_SCHEDULER_HOUR
(2 h du matin par défaut, heure de l'usine). Attend que la base soit prête et migrée
avant de travailler : le service peut démarrer en même temps que l'application.
"""
import logging
import os
import time

from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, close_old_connections, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import DatabaseError
from django.utils import timezone

from .generate_preventive import run_for_all_tenants

logger = logging.getLogger("easymaint")


def database_ready():
    try:
        connection = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(connection)
        return not executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DatabaseError:
        return False


class Command(BaseCommand):
    help = "Boucle des tâches planifiées (génération quotidienne des OT préventifs)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Exécuter une seule fois puis s'arrêter.")

    def monthly_reports(self, now):
        """Rapport mensuel du mois écoulé, s'il manque (module Indicateurs installé)."""
        from django.apps import apps as django_apps

        if not django_apps.is_installed("apps.kpi"):
            return
        from apps.kpi.reports import generate_missing_for_all_tenants

        try:
            created = generate_missing_for_all_tenants()
            if created:
                self.stdout.write(f"{now:%d/%m/%Y %H:%M} · rapports mensuels : {created} produit(s).")
        except Exception:
            logger.exception("Échec des rapports mensuels")

    def purge_notifications(self):
        """Efface les notifications anciennes (module Notifications installé)."""
        from django.apps import apps as django_apps

        if not django_apps.is_installed("apps.notifications"):
            return
        from apps.notifications.services import purge

        try:
            purge()
        except Exception:
            logger.exception("Échec du nettoyage des notifications")

    def handle(self, *args, **options):
        hour = int(os.environ.get("EASYMAINT_SCHEDULER_HOUR", "2"))
        self.stdout.write(f"Planificateur EasyMaint démarré : génération du préventif chaque jour à {hour} h.")
        last_run = None
        while True:
            close_old_connections()
            if not database_ready():
                self.stdout.write("Base de données pas encore prête ou migrations en attente, nouvel essai dans 30 s.")
                time.sleep(30)
                continue
            now = timezone.localtime()
            if last_run is None or (now.date() != last_run and now.hour >= hour):
                try:
                    results = run_for_all_tenants()
                    total = sum(results.values())
                    self.stdout.write(f"{now:%d/%m/%Y %H:%M} · préventif : {total} OT créé(s).")
                except Exception:
                    logger.exception("Échec de la génération du préventif")
                self.monthly_reports(now)
                self.purge_notifications()
                last_run = now.date()
                if options["once"]:
                    return
            time.sleep(60)
