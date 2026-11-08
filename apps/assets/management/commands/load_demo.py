"""
Données de démonstration réalistes : une usine de plasturgie, ses unités,
une trentaine d'équipements, leurs compteurs et douze semaines de relevés.

    python manage.py load_demo --password "MotDePasseDemo-2026"
La démonstration est dans la langue de l'installation (EASYMAINT_LANGUAGE) ; --lang permet de forcer
une autre langue (dans ce cas, choisir aussi un autre --code, par exemple demo-en).

Crée l'entreprise « demo » si elle n'existe pas, un utilisateur par rôle, puis le
patrimoine. Relancer la commande ne crée pas de doublons.
"""
from datetime import date, timedelta

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone, translation

from apps.accounts.models import Role, User
from apps.accounts.services import create_tenant, ensure_default_roles
from apps.assets.models import Equipment, EquipmentFamily, Location, Manufacturer, Meter
from apps.assets.services import record_reading
from apps.core.demo_i18n import _suffix, demo_user, set_username_suffix
from apps.core.models import Tenant
from apps.core.tenancy import tenant_context

USERS = [
    # identifiant, prénom, nom, rôle, fonction
    ("s.bensalah", "Sami", "Ben Salah", "maintenance_manager", "Responsable maintenance"),
    ("a.mejri", "Amel", "Mejri", "maintenance_engineer", "Ingénieure fiabilité"),
    ("r.jaziri", "Ridha", "Jaziri", "team_leader", "Chef d'équipe mécanique"),
    ("k.trabelsi", "Karim", "Trabelsi", "technician", "Technicien mécanicien"),
    ("n.chaabane", "Nour", "Chaabane", "technician", "Technicienne électricienne"),
    ("h.ayari", "Hatem", "Ayari", "technician", "Technicien hydraulicien"),
    ("m.saidi", "Mouna", "Saidi", "storekeeper", "Magasinière"),
    ("m.gharbi", "Mohamed", "Gharbi", "production_manager", "Chef de production"),
    ("l.hammami", "Leila", "Hammami", "management", "Directrice d'usine"),
]

LOCATIONS = [
    # code, nom, type, code parent
    ("BA", "Usine Ben Arous", "site", None),
    ("BA-INJ", "Unité Injection", "workshop", "BA"),
    ("BA-INJ-L1", "Ligne 1", "line", "BA-INJ"),
    ("BA-INJ-L2", "Ligne 2", "line", "BA-INJ"),
    ("BA-EXT", "Unité Extrusion", "workshop", "BA"),
    ("BA-EXT-L1", "Ligne extrusion film", "line", "BA-EXT"),
    ("BA-CDT", "Unité Conditionnement", "workshop", "BA"),
    ("BA-CDT-Z1", "Zone ensachage", "zone", "BA-CDT"),
    ("BA-UTL", "Utilités", "workshop", "BA"),
    ("BA-UTL-AIR", "Local compresseurs", "zone", "BA-UTL"),
    ("BA-UTL-ELEC", "Poste électrique", "zone", "BA-UTL"),
]

FAMILIES = [
    ("PRS", "Presses", None), ("PRS-INJ", "Injection plastique", "PRS"),
    ("EXT", "Extrudeuses", None),
    ("CMP", "Compresseurs et air comprimé", None),
    ("MAN", "Manutention", None), ("MAN-CNV", "Convoyeurs", "MAN"),
    ("CDT", "Conditionnement", None),
    ("THR", "Thermique", None), ("THR-REF", "Refroidissement", "THR"),
    ("ELE", "Électricité", None),
    ("HYD", "Hydraulique", None),
]

MANUFACTURERS = ["Engel", "Arburg", "Bausano", "Atlas Copco", "SEW-Eurodrive", "Schneider Electric", "Wittmann", "Piovan"]

# code, désignation, famille, localisation, fabricant, modèle, n° série, mise en service, criticité, état, parent, compteurs
EQUIPMENT = [
    ("PRS-INJ-01", "Presse à injection 220 t", "PRS-INJ", "BA-INJ-L1", "Engel", "victory 220", "2017-6612-04", "2017-09-12", "A", "in_service", None, [("Heures de fonctionnement", "hours", 24180), ("Cycles", "cycles", 1987400)]),
    ("PRS-INJ-02", "Presse à injection 220 t", "PRS-INJ", "BA-INJ-L1", "Engel", "victory 220", "2017-6612-05", "2017-09-12", "A", "in_service", None, [("Heures de fonctionnement", "hours", 23610)]),
    ("PRS-INJ-03", "Presse à injection 350 t", "PRS-INJ", "BA-INJ-L2", "Engel", "victory 350", "2019-8842-17", "2019-03-15", "A", "broken", None, [("Heures de fonctionnement", "hours", 18432), ("Cycles", "cycles", 1254300)]),
    ("PRS-INJ-03-GH", "Groupe hydraulique", "HYD", "BA-INJ-L2", "Engel", "", "", "2019-03-15", "A", "in_service", "PRS-INJ-03", []),
    ("PRS-INJ-03-TH", "Thermorégulateur moule", "THR", "BA-INJ-L2", "Wittmann", "Tempro plus D", "TD-55120", "2019-03-15", "B", "in_service", "PRS-INJ-03", []),
    ("PRS-INJ-04", "Presse à injection 150 t", "PRS-INJ", "BA-INJ-L2", "Arburg", "Allrounder 470", "AR-470-3381", "2021-05-03", "B", "in_service", None, [("Heures de fonctionnement", "hours", 11920)]),
    ("ROB-INJ-04", "Robot de dépose", "MAN", "BA-INJ-L2", "Wittmann", "W818", "W818-2207", "2021-05-03", "C", "in_service", "PRS-INJ-04", []),
    ("SEC-INJ-01", "Sécheur de granulés", "THR", "BA-INJ", "Piovan", "DS 403", "PV-40312", "2018-02-20", "B", "in_service", None, [("Heures de fonctionnement", "hours", 30150)]),
    ("EXT-01", "Extrudeuse bivis", "EXT", "BA-EXT-L1", "Bausano", "MD 2.70", "BZ-27-0915", "2016-11-07", "A", "in_service", None, [("Heures de fonctionnement", "hours", 41270)]),
    ("EXT-01-MR", "Motoréducteur principal", "EXT", "BA-EXT-L1", "SEW-Eurodrive", "X3FS", "SEW-88412", "2016-11-07", "A", "in_service", "EXT-01", []),
    ("EXT-01-CAL", "Calandre de refroidissement", "THR-REF", "BA-EXT-L1", "Bausano", "", "BZ-CAL-0915", "2016-11-07", "B", "in_service", "EXT-01", []),
    ("CNV-L1", "Convoyeur ligne 1", "MAN-CNV", "BA-INJ-L1", None, "", "", "2017-09-12", "C", "in_service", None, []),
    ("CNV-L2", "Convoyeur ligne 2", "MAN-CNV", "BA-INJ-L2", None, "", "", "2019-03-15", "B", "in_service", None, [("Heures de fonctionnement", "hours", 15020)]),
    ("ENS-04", "Ensacheuse verticale", "CDT", "BA-CDT-Z1", None, "", "", "2020-01-14", "B", "broken", None, [("Cycles", "cycles", 3480200)]),
    ("FIL-01", "Filmeuse de palettes", "CDT", "BA-CDT-Z1", None, "", "", "2020-06-02", "C", "stopped", None, []),
    ("CMP-01", "Compresseur à vis 37 kW", "CMP", "BA-UTL-AIR", "Atlas Copco", "GA 37", "AII-581220", "2015-04-28", "A", "in_service", None, [("Heures de fonctionnement", "hours", 52310)]),
    ("CMP-02", "Compresseur à vis 37 kW", "CMP", "BA-UTL-AIR", "Atlas Copco", "GA 37", "AII-640971", "2019-07-15", "A", "in_service", None, [("Heures de fonctionnement", "hours", 27890)]),
    ("SEC-AIR-01", "Sécheur d'air frigorifique", "CMP", "BA-UTL-AIR", "Atlas Copco", "FD 95", "FD-77105", "2015-04-28", "B", "in_service", None, []),
    ("GF-01", "Groupe froid eau glacée", "THR-REF", "BA-UTL", None, "", "", "2018-05-10", "A", "in_service", None, [("Heures de fonctionnement", "hours", 33400)]),
    ("TGBT-01", "Tableau général basse tension", "ELE", "BA-UTL-ELEC", "Schneider Electric", "Prisma", "", "2015-03-01", "A", "in_service", None, []),
    ("TR-01", "Transformateur 1 000 kVA", "ELE", "BA-UTL-ELEC", "Schneider Electric", "Trihal", "TR-1000-2214", "2015-03-01", "A", "in_service", None, []),
]


class Command(BaseCommand):
    help = "Charge des données de démonstration réalistes (entreprise « demo »)."

    def add_arguments(self, parser):
        parser.add_argument("--code", default="demo", help="Code de l'entreprise de démonstration")
        parser.add_argument("--password", required=True, help="Mot de passe donné à tous les comptes de démonstration")
        parser.add_argument("--lang", choices=["fr", "en"], default="", help="Langue des données (par défaut : celle de l'installation)")

    def handle(self, *args, **options):
        lang = options["lang"] or settings.LANGUAGE_CODE[:2]
        code = options["code"]
        # Identifiants distincts pour une seconde démonstration (s.bensalah.en) : les deux peuvent coexister.
        token = set_username_suffix("" if code == "demo" else "." + code.removeprefix("demo-"))
        try:
            with translation.override(lang):
                self._load(code, options["password"], lang)
        finally:
            _suffix.reset(token)

    @transaction.atomic
    def _load(self, code, password, lang):
        tenant = Tenant.objects.filter(code=code).first()
        if tenant is None:
            tenant, _admin = create_tenant(
                name="Société de démonstration", code=code, admin_username=f"admin.{code}", admin_password=password,
                admin_first_name="Admin", admin_last_name="Démo",
            )
            self.stdout.write(f"Entreprise « {tenant} » créée.")
        ensure_default_roles(tenant)

        with tenant_context(tenant):
            roles = {role.code: role for role in Role.objects.all()}
            for base, first, last, role_code, job in USERS:
                username = demo_user(base)
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={"first_name": first, "last_name": last, "tenant": tenant, "role": roles[role_code], "job_title": job},
                )
                if created:
                    user.set_password(password)
                    user.save()
                elif user.tenant_id != tenant.pk:
                    raise CommandError(f"L'identifiant {username} existe déjà dans une autre entreprise.")

            locations = {}
            for loc_code, name, kind, parent_code in LOCATIONS:
                locations[loc_code], _ = Location.objects.get_or_create(
                    code=loc_code, defaults={"name": name, "kind": kind, "parent": locations.get(parent_code)},
                )
            families = {}
            for fam_code, name, parent_code in FAMILIES:
                families[fam_code], _ = EquipmentFamily.objects.get_or_create(
                    code=fam_code, defaults={"name": name, "parent": families.get(parent_code)},
                )
            manufacturers = {name: Manufacturer.objects.get_or_create(name=name)[0] for name in MANUFACTURERS}
            responsible = User.objects.filter(username=demo_user("k.trabelsi")).first()

            created_count, equipment_by_code = 0, {}
            for (eq_code, designation, family, location, maker, model, serial, commissioned,
                 criticality, status, parent, meters) in EQUIPMENT:
                equipment, created = Equipment.objects.get_or_create(
                    code=eq_code,
                    defaults={
                        "designation": designation, "family": families[family], "location": locations[location],
                        "manufacturer": manufacturers.get(maker), "model": model, "serial_number": serial,
                        "commissioning_date": date.fromisoformat(commissioned), "criticality": criticality,
                        "status": status, "parent": equipment_by_code.get(parent),
                        "responsible": responsible if criticality == "A" else None,
                        "required_hours_per_day": 24 if family in ("CMP", "THR-REF", "ELE") else 16,
                    },
                )
                equipment_by_code[eq_code] = equipment
                if created:
                    created_count += 1
                    self._create_meters(equipment, meters, responsible)

            interventions = 0
            if django_apps.is_installed("apps.workorders"):
                from apps.workorders.demo import load as load_interventions

                admin = User.objects.filter(username=f"admin.{code}").first()
                interventions = load_interventions(tenant, author=admin)
            generated = 0
            if django_apps.is_installed("apps.preventive"):
                from apps.preventive.demo import load as load_preventive

                generated = load_preventive(tenant, author=User.objects.filter(username=f"admin.{code}").first())
            sessions = 0
            if django_apps.is_installed("apps.condition"):
                from apps.condition.demo import load as load_condition

                sessions = load_condition(tenant)
            budgets = 0
            articles = 0
            if django_apps.is_installed("apps.inventory"):
                from apps.inventory.demo import load as load_inventory

                articles = load_inventory(tenant, author=User.objects.filter(username=f"admin.{code}").first())
            if django_apps.is_installed("apps.finance"):
                from apps.finance.demo import load as load_finance

                budgets = load_finance(tenant, author=User.objects.filter(username=f"admin.{code}").first())

            if lang == "en":
                from apps.core.demo_i18n import translate_tenant

                translate_tenant(tenant)

        self.stdout.write(self.style.SUCCESS(
            f"Démonstration prête : {created_count} équipements créés, {interventions} ordres de travail, "
            f"plans préventifs chargés ({generated} OT généré(s) automatiquement), {sessions} tournées de mesures, {articles} articles en stock, {budgets} budgets. "
            f"Comptes : admin.{code}, " + ", ".join(demo_user(u[0]) for u in USERS) + " (même mot de passe)."
        ))

    def _create_meters(self, equipment, meters, user):
        """Douze relevés hebdomadaires cohérents (valeurs croissantes) pour chaque compteur."""
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        for index, (name, kind, current) in enumerate(meters):
            meter = Meter.objects.create(equipment=equipment, name=name, kind=kind)
            weekly = {"hours": 112 if equipment.required_hours_per_day == 16 else 168, "cycles": 21000, "distance": 300}.get(kind, 10)
            if equipment.status == Equipment.Status.STOPPED:
                weekly = 0
            weeks = 12
            # Un compteur volontairement en retard de relevé, pour illustrer l'alerte du tableau de bord.
            last_offset = 45 if equipment.code == "SEC-INJ-01" else (2 + index)
            for week in range(weeks, -1, -1):
                value = current - weekly * week
                reading_at = now - timedelta(days=last_offset + 7 * week, hours=3)
                record_reading(meter, max(value, 0), reading_at=reading_at, user=user)
