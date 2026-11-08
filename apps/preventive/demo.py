"""
Plans préventifs de démonstration (appelés par `load_demo`, après les interventions).

Les plans sont reliés aux OT préventifs déjà présents dans la démonstration, ajoutent
quatre semaines d'historique du contrôle hebdomadaire, puis la génération automatique
est lancée une fois pour montrer son fonctionnement.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.assets.models import Equipment, Meter
from apps.core.demo_i18n import demo_user
from apps.core.services import next_document_number
from apps.workforce.models import Skill, Team, Technician
from apps.workorders.models import StatusLog, TimeEntry, WorkOrder
from apps.workorders.services import compute_costs

from .models import PlanChecklistItem, PlanPart, PreventivePlan
from .services import generate_due_work_orders


def _plan(code, equipment, name, operations, *, checklist=(), parts=(), technicians=(), team=None, skills=(), **trigger):
    plan = PreventivePlan.objects.create(code=code, equipment=equipment, name=name, operations=operations, team=team, **trigger)
    if technicians:
        plan.technicians.set(technicians)
    if skills:
        plan.skills.set(skills)
    for position, label in enumerate(checklist, start=1):
        PlanChecklistItem.objects.create(plan=plan, position=position, label=label)
    for reference, designation, quantity in parts:
        PlanPart.objects.create(plan=plan, reference=reference, designation=designation, quantity=Decimal(quantity))
    return plan


def _link(plan, title):
    """Rattache au plan les OT préventifs existants portant cet intitulé."""
    for wo in WorkOrder.objects.filter(kind=WorkOrder.Kind.PREVENTIVE, preventive_plan__isnull=True, title=title, equipment=plan.equipment):
        wo.preventive_plan = plan
        wo.original_due_date = wo.original_due_date or wo.due_date or wo.planned_date or timezone.localdate()
        if wo.due_date is None:
            wo.due_date = wo.original_due_date
        wo.save(update_fields=["preventive_plan", "original_due_date", "due_date", "updated_at"])


def load(tenant, *, author):
    if PreventivePlan.objects.exists():
        return 0
    today = timezone.localdate()
    now = timezone.now()
    eq = {e.code: e for e in Equipment.objects.all()}
    tech = {t.employee_number: t for t in Technician.objects.all()}
    teams = {t.name: t for t in Team.objects.all()}
    skills = {s.code: s for s in Skill.objects.all()}
    manager = User.objects.filter(username=demo_user("s.bensalah"), tenant=tenant).first() or author

    def meter(code, name):
        return Meter.objects.filter(equipment=eq[code], name=name).first()

    def pick(*numbers):
        return [tech[n] for n in numbers if n in tech]

    team_a = teams.get("Équipe A · mécanique")

    weekly = _plan(
        "PP-INJ03-SEC", eq["PRS-INJ-03"], "Contrôle hebdomadaire des sécurités",
        "Vérifier le fonctionnement de toutes les sécurités de la presse.",
        instructions="Presse à l'arrêt, moule ouvert. Ne jamais shunter une sécurité pour la tester.",
        checklist=["Arrêts d'urgence (3)", "Portes de protection et barrières immatérielles", "Clapet de sécurité hydraulique", "Voyants et alarmes"],
        technicians=pick("E-204"), skills=[skills[c] for c in ("ELE",) if c in skills],
        trigger_mode="calendar", period_value=1, period_unit="week", next_due_date=today + timedelta(days=3),
        lead_days=3, estimated_hours=Decimal("0.5"), priority=3,
    )
    _plan(
        "PP-INJ03-FILT", eq["PRS-INJ-03"], "Remplacement filtres hydrauliques",
        "Remplacer les cartouches de filtration retour et pression du groupe hydraulique.",
        checklist=["Consigner le groupe hydraulique", "Remplacer les cartouches", "Contrôler l'indicateur de colmatage", "Essai et contrôle des fuites"],
        parts=[("PDR-HYD-0021", "Cartouche filtre retour 10 µm", "2"), ("PDR-HYD-0022", "Cartouche filtre pression 5 µm", "1")],
        technicians=pick("M-118"), trigger_mode="calendar", period_value=6, period_unit="month",
        next_due_date=today + timedelta(days=25), lead_days=14, estimated_hours=Decimal("1.5"),
    )
    cmp02 = _plan(
        "PP-CMP02-4000", eq["CMP-02"], "Remplacement filtres huile et air (4 000 h)",
        "Remplacer filtre à huile, filtre à air et séparateur selon la gamme constructeur.",
        checklist=["Consigner et purger le compresseur", "Remplacer filtre à huile", "Remplacer filtre à air", "Contrôler le niveau d'huile", "Essai en charge"],
        parts=[("AC-2901", "Kit filtres GA 37 (huile + air)", "1"), ("AC-ROTO", "Huile Roto-Inject Fluid (L)", "5")],
        technicians=pick("M-118"), team=team_a, trigger_mode="meter",
        meter=meter("CMP-02", "Heures de fonctionnement"), meter_interval=Decimal("4000"), meter_lead=Decimal("150"),
        estimated_hours=Decimal("2"),
    )
    cmp02_meter = cmp02.meter
    if cmp02_meter is not None:
        cmp02.last_done_meter = cmp02_meter.current_value - Decimal("3950")
        cmp02.save(update_fields=["last_done_meter", "updated_at"])
    _link(cmp02, "Remplacement filtres huile et air (4 000 h)")

    ext = _plan(
        "PP-EXT01-VID", eq["EXT-01"], "Vidange réducteur principal (2 000 h)",
        "Vidanger le réducteur principal, remplacer l'huile et nettoyer le bouchon magnétique.",
        checklist=["Prélever un échantillon d'huile avant vidange", "Vidanger et rincer", "Nettoyer le bouchon magnétique", "Remplir et contrôler le niveau"],
        parts=[("LUB-ISO220", "Huile engrenages ISO VG 220 (L)", "40")],
        technicians=pick("M-118"), trigger_mode="meter", meter=meter("EXT-01", "Heures de fonctionnement"),
        meter_interval=Decimal("2000"), meter_lead=Decimal("100"), estimated_hours=Decimal("3"),
    )
    if ext.meter is not None:
        ext.last_done_meter = ext.meter.current_value - Decimal("150")
        ext.last_done_date = today - timedelta(days=6)
        ext.save(update_fields=["last_done_meter", "last_done_date", "updated_at"])
    _link(ext, "Vidange réducteur principal (2 000 h)")

    gf = _plan(
        "PP-GF01-ETAN", eq["GF-01"], "Contrôle étanchéité circuit frigorifique",
        "Contrôle d'étanchéité réglementaire du circuit frigorifique.",
        checklist=["Détecteur électronique sur tous les raccords", "Relevé des pressions HP / BP", "Mise à jour du registre"],
        team=team_a, trigger_mode="calendar", period_value=3, period_unit="month",
        next_due_date=today - timedelta(days=7), lead_days=10, estimated_hours=Decimal("3"),
    )
    _link(gf, "Contrôle étanchéité circuit frigorifique")
    gf_cond = _plan(
        "PP-GF01-COND", eq["GF-01"], "Nettoyage condenseur",
        "Nettoyer les ailettes du condenseur et contrôler les ventilateurs.",
        technicians=pick("M-112"), trigger_mode="calendar", period_value=6, period_unit="month",
        next_due_date=today + timedelta(days=60), lead_days=14, estimated_hours=Decimal("2"),
        last_done_date=today - timedelta(days=120),
    )
    _link(gf_cond, "Nettoyage condenseur")
    cmp01 = _plan(
        "PP-CMP01-AN", eq["CMP-01"], "Contrôle annuel des soupapes",
        "Contrôle et tarage des soupapes de sécurité, révision générale annuelle.",
        technicians=pick("M-112"), trigger_mode="both", period_value=1, period_unit="year",
        next_due_date=today + timedelta(days=215), lead_days=21, meter=meter("CMP-01", "Heures de fonctionnement"),
        meter_interval=Decimal("8000"), meter_lead=Decimal("200"), estimated_hours=Decimal("1.5"),
        last_done_date=today - timedelta(days=150),
    )
    if cmp01.meter is not None:
        cmp01.last_done_meter = cmp01.meter.current_value - Decimal("3500")
        cmp01.save(update_fields=["last_done_meter", "updated_at"])
    _link(cmp01, "Contrôle annuel des soupapes")
    sec = _plan(
        "PP-SEC01-FILT", eq["SEC-INJ-01"], "Nettoyage filtres du sécheur",
        "Démonter, souffler et remonter les filtres du sécheur de granulés.",
        technicians=pick("M-101"), trigger_mode="calendar", period_value=2, period_unit="week",
        next_due_date=today, lead_days=2, estimated_hours=Decimal("1"),
    )
    _link(sec, "Nettoyage filtres du sécheur")
    _plan(
        "PP-CNV2-GRAI", eq["CNV-L2"], "Graissage paliers et tension de bande",
        "Graisser les paliers du convoyeur et contrôler la tension et l'alignement de la bande.",
        checklist=["Graisser les 6 paliers", "Contrôler la tension de bande", "Contrôler l'alignement"],
        parts=[("LUB-EP2", "Graisse EP2 (cartouche)", "1")], team=team_a,
        trigger_mode="calendar", period_value=1, period_unit="month", next_due_date=today + timedelta(days=12),
        lead_days=5, estimated_hours=Decimal("1"),
    )

    # Historique du contrôle hebdomadaire : 4 semaines, dont une réalisée avec deux jours de retard.
    electrician = tech.get("E-204")
    for weeks, delay in ((4, 0), (3, 0), (2, 2), (1, 0)):
        due = weekly.next_due_date - timedelta(weeks=weeks)
        done = due + timedelta(days=delay)
        start = timezone.make_aware(datetime(done.year, done.month, done.day, 7, 30))
        end = start + timedelta(minutes=30)
        if end > now:
            continue
        wo = WorkOrder.objects.create(
            number=next_document_number("OT"), kind=WorkOrder.Kind.PREVENTIVE, equipment=weekly.equipment,
            title=weekly.name, description=weekly.operations, priority=3, status=WorkOrder.Status.VALIDATED,
            planned_date=done, due_date=done, original_due_date=due, preventive_plan=weekly,
            estimated_hours=weekly.estimated_hours, started_at=start, finished_at=end,
            work_done="Toutes les sécurités sont opérationnelles.", validated_by=manager, validated_at=end + timedelta(hours=4),
            created_by=manager,
        )
        if electrician is not None:
            wo.technicians.add(electrician)
            TimeEntry.objects.create(work_order=wo, technician=electrician, started_at=start, ended_at=end,
                                     hours=Decimal("0.50"), hourly_rate=electrician.hourly_rate)
        costs = compute_costs(wo)
        WorkOrder.objects.filter(pk=wo.pk).update(labour_cost=costs["labour"], total_cost=costs["total"])
        for status, at in (("assigned", start - timedelta(days=3)), ("in_progress", start), ("done", end), ("validated", end + timedelta(hours=4))):
            StatusLog.objects.create(work_order=wo, to_status=status, user=manager, at=at)
    weekly.last_done_date = weekly.next_due_date - timedelta(weeks=1)
    weekly.save(update_fields=["last_done_date", "updated_at"])

    created = generate_due_work_orders(today=today)
    return len(created)
