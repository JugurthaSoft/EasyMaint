"""
Données de démonstration des interventions (appelées par `load_demo`).

Crée des techniciens reliés aux comptes de démonstration, deux équipes, des
compétences, des sous-traitants, des codes de défaillance, un historique d'OT
validés sur six mois et quelques OT en cours dans tous les états.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.assets.models import Equipment
from apps.core.demo_i18n import demo_user
from apps.core.services import next_document_number
from apps.workforce.models import Contractor, Skill, Team, Technician

from . import services
from .models import (
    ChecklistItem,
    Downtime,
    FailureCode,
    PartUsage,
    StatusLog,
    TimeEntry,
    WorkOrder,
    WorkRequest,
)

TECHNICIANS = [
    # matricule, prénom, nom, identifiant, spécialité, équipe, coût horaire
    ("M-101", "Ridha", "Jaziri", "r.jaziri", "Mécanique", "A", "18.500"),
    ("M-112", "Karim", "Trabelsi", "k.trabelsi", "Mécanique", "A", "14.200"),
    ("M-118", "Hatem", "Ayari", "h.ayari", "Hydraulique", "A", "14.800"),
    ("E-204", "Nour", "Chaabane", "n.chaabane", "Électricité", "B", "15.600"),
    ("E-209", "Walid", "Mansouri", None, "Électricité et automatisme", "B", "13.900"),
]

SKILLS = [("MEC", "Mécanique"), ("HYD", "Hydraulique"), ("ELE", "Électricité"), ("AUT", "Automatisme"), ("SOU", "Soudure")]

FAILURE_CODES = [
    ("mode", "FUITE", "Fuite"), ("mode", "BRUIT", "Bruit ou vibration anormale"), ("mode", "ARRET", "Arrêt intempestif"),
    ("mode", "SURCH", "Échauffement"), ("cause", "USURE", "Usure normale"), ("cause", "JOINT", "Joint usé ou durci"),
    ("cause", "LUBRI", "Défaut de lubrification"), ("cause", "CAPT", "Capteur défaillant"),
    ("cause", "ELEC", "Défaut électrique"), ("cause", "MAUV", "Mauvaise utilisation"),
    ("remedy", "REMPL", "Remplacement de la pièce"), ("remedy", "REGL", "Réglage"), ("remedy", "NETT", "Nettoyage"),
]

# équipement, intitulé, type, il y a N jours, heures, cause, technicien, coût pièces, durée d'arrêt (h)
HISTORY = [
    ("PRS-INJ-03", "Remplacement thermocouple zone 3", "corrective", 19, "1.8", "CAPT", "E-204", "86.400", "1.8"),
    ("PRS-INJ-03", "Remplacement roulement pompe hydraulique", "conditional", 35, "4.0", "USURE", "M-118", "412.600", "4.0"),
    ("PRS-INJ-03", "Flexible haute pression éclaté", "corrective", 46, "2.5", "USURE", "M-118", "238.000", "2.5"),
    ("EXT-01", "Vidange réducteur principal (2 000 h)", "preventive", 6, "3.0", None, "M-118", "540.000", None),
    ("EXT-01", "Résistance de fourreau zone 2 hors service", "corrective", 58, "2.0", "ELEC", "E-204", "195.000", "2.0"),
    ("CMP-02", "Remplacement séparateur huile", "corrective", 72, "3.5", "USURE", "M-112", "620.000", "3.5"),
    ("CNV-L2", "Bande déportée côté entraînement", "corrective", 88, "1.5", "MAUV", "M-112", "0", "1.0"),
    ("ENS-04", "Capteur présence sachet", "corrective", 101, "1.0", "CAPT", "E-209", "64.000", "1.0"),
    ("GF-01", "Nettoyage condenseur", "preventive", 120, "2.0", None, "M-112", "0", None),
    ("PRS-INJ-01", "Fuite huile vérin d'éjection", "corrective", 133, "2.0", "JOINT", "M-118", "75.500", "2.0"),
    ("CMP-01", "Contrôle annuel des soupapes", "preventive", 150, "1.5", None, "M-112", "0", None),
]


def load(tenant, *, author):
    if WorkOrder.objects.exists():
        return 0
    now = timezone.now()
    skills = {code: Skill.objects.get_or_create(code=code, defaults={"name": name})[0] for code, name in SKILLS}
    teams = {
        "A": Team.objects.get_or_create(name="Équipe A · mécanique")[0],
        "B": Team.objects.get_or_create(name="Équipe B · électricité")[0],
    }
    technicians = {}
    for number, first, last, username, specialty, team, rate in TECHNICIANS:
        user = User.objects.filter(username=demo_user(username), tenant=tenant).first() if username else None
        technician, _ = Technician.objects.get_or_create(
            employee_number=number,
            defaults={"first_name": first, "last_name": last, "user": user, "specialty": specialty,
                      "team": teams[team], "hourly_rate": Decimal(rate), "overtime_rate": (Decimal(rate) * Decimal("1.25")).quantize(Decimal("0.001")),
                      "function": "Technicien de maintenance"},
        )
        technician.skills.add(skills["ELE" if specialty.startswith("Élec") else ("HYD" if specialty == "Hydraulique" else "MEC")])
        technicians[number] = technician
    teams["A"].leader = technicians["M-101"]
    teams["A"].save()
    teams["B"].leader = technicians["E-204"]
    teams["B"].save()
    Contractor.objects.get_or_create(name="Électro Services Sud", defaults={"specialties": "Haute tension, TGBT", "phone": "71 000 000"})
    Contractor.objects.get_or_create(name="Rectif Mécanique", defaults={"specialties": "Rectification, usinage"})
    codes = {}
    for kind, code, name in FAILURE_CODES:
        codes[code] = FailureCode.objects.get_or_create(kind=kind, code=code, defaults={"name": name})[0]

    equipment = {e.code: e for e in Equipment.objects.all()}
    manager = User.objects.filter(username=demo_user("s.bensalah"), tenant=tenant).first() or author

    # Historique : OT validés, avec temps, pièces, arrêts et coûts figés
    for code, title, kind, days, hours, cause, tech, parts_cost, stop_hours in sorted(HISTORY, key=lambda h: -h[3]):
        technician = technicians[tech]
        start = now - timedelta(days=days, hours=3)
        end = start + timedelta(hours=float(hours))
        wo = WorkOrder.objects.create(
            number=next_document_number("OT", year=start.year), kind=kind, equipment=equipment[code], title=title,
            priority=2 if kind == "corrective" else 3, status=WorkOrder.Status.VALIDATED,
            production_stopped=stop_hours is not None, planned_date=start.date(), due_date=start.date(),
            estimated_hours=Decimal(hours), started_at=start, finished_at=end,
            failure_cause=codes.get(cause), work_done=f"{title} : intervention réalisée, essais conformes.",
            validated_by=manager, validated_at=end + timedelta(hours=20), created_by=manager,
        )
        wo.technicians.add(technician)
        TimeEntry.objects.create(work_order=wo, technician=technician, started_at=start, ended_at=end,
                                 hours=Decimal(hours), hourly_rate=technician.hourly_rate)
        if Decimal(parts_cost):
            PartUsage.objects.create(work_order=wo, designation=f"Pièces : {title.lower()}", quantity=1, unit_cost=Decimal(parts_cost))
        if stop_hours:
            Downtime.objects.create(equipment=wo.equipment, work_order=wo, started_at=start - timedelta(minutes=40),
                                    ended_at=start + timedelta(hours=float(stop_hours)))
        costs = services.compute_costs(wo)
        WorkOrder.objects.filter(pk=wo.pk).update(
            labour_cost=costs["labour"], parts_cost=costs["parts"], external_cost=costs["external"],
            other_cost=costs["other"], total_cost=costs["total"], created_at=start - timedelta(hours=1),
        )
        for status, at in (("assigned", start - timedelta(hours=1)), ("in_progress", start), ("done", end), ("validated", end + timedelta(hours=20))):
            StatusLog.objects.create(work_order=wo, to_status=status, user=manager, at=at)

    # En cours : la presse PRS-INJ-03 est en panne depuis deux jours (cohérent avec son état)
    press = equipment["PRS-INJ-03"]
    stop_start = now - timedelta(days=2, hours=4)
    request_obj = WorkRequest.objects.create(
        number=next_document_number("DI"), equipment=press, description="Fuite d'huile sur le vérin de fermeture\nFuite importante côté plateau mobile en début de poste.",
        priority=1, production_stopped=True, requested_by=User.objects.filter(username=demo_user("m.gharbi")).first(), requested_at=stop_start,
    )
    Downtime.objects.create(equipment=press, work_request=request_obj, started_at=stop_start)
    wo = services.accept_request(request_obj, user=manager)
    wo.due_date = (now - timedelta(days=2)).date()
    wo.description = request_obj.description
    wo.save()
    wo.technicians.add(technicians["M-112"])
    WorkOrder.objects.filter(pk=wo.pk).update(status=WorkOrder.Status.IN_PROGRESS, started_at=stop_start + timedelta(hours=1))
    StatusLog.objects.create(work_order=wo, from_status="to_plan", to_status="in_progress", user=manager, at=stop_start + timedelta(hours=1))
    for position, label in enumerate([
        "Consigner la presse (énergie hydraulique et électrique)", "Purger la pression du circuit",
        "Remplacer les joints du vérin", "Contrôler le niveau d'huile et compléter", "Essai à vide : 10 cycles sans fuite",
    ], start=1):
        ChecklistItem.objects.create(work_order=wo, label=label, position=position, is_done=position <= 2)
    TimeEntry.objects.create(work_order=wo, technician=technicians["M-112"], started_at=stop_start + timedelta(hours=1),
                             ended_at=stop_start + timedelta(hours=3), hours=Decimal("2.00"), hourly_rate=technicians["M-112"].hourly_rate)

    # Ensacheuse en panne : demande pas encore traitée
    bagger = equipment["ENS-04"]
    request_new = WorkRequest.objects.create(
        number=next_document_number("DI"), equipment=bagger, description="Le capteur de présence sachet ne détecte plus rien.",
        priority=2, production_stopped=True, requested_by=User.objects.filter(username=demo_user("m.gharbi")).first(), requested_at=now - timedelta(hours=5),
    )
    Downtime.objects.create(equipment=bagger, work_request=request_new, started_at=now - timedelta(hours=5))

    # Autres OT ouverts dans différents états
    services.create_work_order(user=manager, equipment=equipment["CNV-L2"], title="Bande déportée côté entraînement", kind="corrective",
                               priority=2, planned_date=(now + timedelta(days=1)).date(), due_date=(now + timedelta(days=1)).date(),
                               estimated_hours=Decimal("1.5"), technicians=[technicians["E-204"]])
    waiting = services.create_work_order(user=manager, equipment=equipment["CMP-02"], title="Remplacement filtres huile et air (4 000 h)",
                                         kind="preventive", priority=3, due_date=(now - timedelta(days=4)).date(),
                                         estimated_hours=Decimal("2"), technicians=[technicians["M-118"]])
    WorkOrder.objects.filter(pk=waiting.pk).update(status=WorkOrder.Status.WAITING_PARTS, waiting_reason="Kit filtres GA 37 commandé", started_at=now - timedelta(days=4))
    services.create_work_order(user=manager, equipment=equipment["GF-01"], title="Contrôle étanchéité circuit frigorifique", kind="preventive",
                               priority=3, due_date=(now - timedelta(days=7)).date(), estimated_hours=Decimal("3"))
    done = services.create_work_order(user=manager, equipment=equipment["SEC-INJ-01"], title="Nettoyage filtres du sécheur", kind="preventive",
                                      priority=3, estimated_hours=Decimal("1"), technicians=[technicians["M-101"]])
    TimeEntry.objects.create(work_order=done, technician=technicians["M-101"], started_at=now - timedelta(hours=6),
                             ended_at=now - timedelta(hours=5), hours=Decimal("1.00"), hourly_rate=technicians["M-101"].hourly_rate)
    WorkOrder.objects.filter(pk=done.pk).update(status=WorkOrder.Status.DONE, work_done="Filtres nettoyés et remontés.",
                                                started_at=now - timedelta(hours=6), finished_at=now - timedelta(hours=5))
    return WorkOrder.objects.count()
