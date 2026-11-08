"""
Données de démonstration du conditionnel (appelées par `load_demo`).

Les seuils de démonstration sont saisis comme le ferait un utilisateur, avec leur
source (norme, constructeur, laboratoire, retour d'expérience) : le logiciel lui-même
n'impose aucun seuil.

Situations illustrées :
- CMP-02 : vibration du palier moteur en hausse jusqu'à l'alarme ; une règle crée une
  demande d'intervention ;
- EXT-01 : fer dans l'huile du réducteur en attention ;
- PRS-INJ-03 : température d'huile hydraulique en attention ;
- le reste des points est dans les seuils.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.assets.models import Equipment
from apps.workforce.models import Technician

from .models import ImportProfile, MeasurementPoint, Parameter, Threshold, TriggerRule
from .services import record_session

PARAMETERS = [
    # code, nom, unité, catégorie, sens
    ("VIB-V", "Vitesse vibratoire", "mm/s RMS", "vibration", "rising"),
    ("VIB-A", "Accélération vibratoire", "m/s²", "vibration", "rising"),
    ("VIB-D", "Déplacement vibratoire", "µm", "vibration", "rising"),
    ("VIB-F", "Fréquence dominante", "Hz", "vibration", "rising"),
    ("HUI-VISC", "Viscosité à 40 °C", "cSt", "oil", "range"),
    ("HUI-TAN", "Indice d'acide (TAN)", "mg KOH/g", "oil", "rising"),
    ("HUI-EAU", "Teneur en eau", "ppm", "oil", "rising"),
    ("HUI-FE", "Fer (Fe)", "ppm", "oil", "rising"),
    ("HUI-CU", "Cuivre (Cu)", "ppm", "oil", "rising"),
    ("HUI-AL", "Aluminium (Al)", "ppm", "oil", "rising"),
    ("HUI-CR", "Chrome (Cr)", "ppm", "oil", "rising"),
    ("HUI-SI", "Silicium (Si)", "ppm", "oil", "rising"),
    ("ISO-4", "Propreté ISO 4406 (> 4 µm)", "code", "oil", "rising"),
    ("ISO-6", "Propreté ISO 4406 (> 6 µm)", "code", "oil", "rising"),
    ("ISO-14", "Propreté ISO 4406 (> 14 µm)", "code", "oil", "rising"),
    ("TEMP", "Température", "°C", "temperature", "rising"),
    ("PRES", "Pression", "bar", "pressure", "range"),
    ("COUR", "Intensité électrique", "A", "current", "rising"),
]

VIB_STANDARD = ("standard", "ISO 20816-3, groupe 2, fixation rigide (valeurs retenues par l'entreprise)")


def _points(eq, parameters):
    specs = [
        # équipement, code, nom, emplacement, direction, paramètres
        ("CMP-02", "MOT-CA-H", "Palier moteur côté accouplement", "Moteur 37 kW, palier côté accouplement", "H", ["VIB-V", "VIB-A", "VIB-F"]),
        ("CMP-02", "MOT-CO-H", "Palier moteur côté opposé", "Moteur 37 kW, palier côté ventilateur", "H", ["VIB-V", "VIB-A"]),
        ("CMP-02", "VIS-H", "Bloc vis", "Carter du bloc vis, côté refoulement", "H", ["VIB-V"]),
        ("EXT-01", "RED-VIB", "Réducteur principal, palier d'entrée", "Réducteur X3FS, arbre d'entrée", "H", ["VIB-V"]),
        ("EXT-01", "RED-HUILE", "Huile du réducteur principal", "Bouchon de prélèvement, carter du réducteur", "", ["HUI-VISC", "HUI-TAN", "HUI-EAU", "HUI-FE", "HUI-CU", "HUI-SI", "ISO-4", "ISO-6", "ISO-14"]),
        ("PRS-INJ-03", "GH-HUILE", "Huile hydraulique", "Réservoir du groupe hydraulique", "", ["TEMP"]),
        ("GF-01", "GF-COMP", "Compresseur frigorifique", "Armoire du groupe froid, départ compresseur", "", ["COUR"]),
    ]
    points = {}
    for eq_code, code, name, position, direction, params in specs:
        if eq_code not in eq:
            continue
        point = MeasurementPoint.objects.create(equipment=eq[eq_code], code=code, name=name, position=position, direction=direction)
        point.parameters.set([parameters[p] for p in params])
        points[(eq_code, code)] = point
    return points


def _threshold(point, parameter, valid_from, source, reference, **levels):
    return Threshold.objects.create(
        point=point, parameter=parameter, valid_from=valid_from, source=source, reference=reference,
        **{key: Decimal(str(value)) for key, value in levels.items()},
    )


def load(tenant, *, author=None):
    if Parameter.objects.exists():
        return 0
    parameters = {}
    for code, name, unit, category, direction in PARAMETERS:
        parameters[code] = Parameter.objects.create(code=code, name=name, unit=unit, category=category, direction=direction)
    eq = {e.code: e for e in Equipment.objects.filter(code__in=["CMP-02", "EXT-01", "PRS-INJ-03", "GF-01"])}
    points = _points(eq, parameters)
    if not points:
        return 0
    today = timezone.localdate()
    since = today - timedelta(days=365)
    P = parameters

    for key in (("CMP-02", "MOT-CA-H"), ("CMP-02", "MOT-CO-H"), ("CMP-02", "VIS-H"), ("EXT-01", "RED-VIB")):
        if key in points:
            _threshold(points[key], P["VIB-V"], since, *VIB_STANDARD, warning_high=2.8, alarm_high=4.5, critical_high=7.1)
    for key in (("CMP-02", "MOT-CA-H"), ("CMP-02", "MOT-CO-H")):
        if key in points:
            _threshold(points[key], P["VIB-A"], since, "experience", "Historique du parc compresseurs", warning_high=10, alarm_high=20, critical_high=30)
    oil = points.get(("EXT-01", "RED-HUILE"))
    if oil:
        _threshold(oil, P["HUI-VISC"], since, "manufacturer", "Huile ISO VG 220 : ±10 % attention, ±15 % alarme",
                   warning_low=198, alarm_low=187, warning_high=242, alarm_high=253)
        _threshold(oil, P["HUI-FE"], since, "laboratory", "Recommandation du laboratoire, réducteurs industriels", warning_high=60, alarm_high=100, critical_high=150)
        _threshold(oil, P["HUI-EAU"], since, "laboratory", "Recommandation du laboratoire", warning_high=500, alarm_high=1000, critical_high=2000)
        _threshold(oil, P["HUI-TAN"], since, "manufacturer", "Fiche technique de l'huile", warning_high=1.5, alarm_high=2.5)
        for code, levels in (("ISO-4", (20, 22, 24)), ("ISO-6", (18, 20, 22)), ("ISO-14", (15, 17, 19))):
            _threshold(oil, P[code], since, "manufacturer", "Classe de propreté visée 18/16/13",
                       warning_high=levels[0], alarm_high=levels[1], critical_high=levels[2])
    hyd = points.get(("PRS-INJ-03", "GH-HUILE"))
    if hyd:
        _threshold(hyd, P["TEMP"], since, "manufacturer", "Notice Engel : huile hydraulique 35 à 55 °C", warning_high=55, alarm_high=60, critical_high=65)
    gf = points.get(("GF-01", "GF-COMP"))
    if gf:
        _threshold(gf, P["COUR"], since, "manufacturer", "Plaque moteur : 52 A nominal", warning_high=48, alarm_high=52, critical_high=55)

    TriggerRule.objects.create(name="Vibration en alarme : demande d'intervention", parameter=P["VIB-V"], min_level="alarm",
                               consecutive=1, action="request", priority=2)
    TriggerRule.objects.create(name="Fer dans l'huile en alarme deux fois de suite : OT conditionnel", parameter=P["HUI-FE"],
                               min_level="alarm", consecutive=2, action="work_order", priority=2)

    techs = {t.employee_number: t for t in Technician.objects.all()}
    vib_tech, oil_tech, elec_tech = techs.get("M-118"), techs.get("M-112"), techs.get("E-204")
    now = timezone.now().replace(minute=0, second=0, microsecond=0)

    def at(days_ago, hour=9):
        return (now - timedelta(days=days_ago)).replace(hour=hour)

    count = 0
    # CMP-02 : tournée vibratoire tous les 14 jours, dégradation progressive du palier côté accouplement.
    if ("CMP-02", "MOT-CA-H") in points:
        ca, co, vis = points[("CMP-02", "MOT-CA-H")], points[("CMP-02", "MOT-CO-H")], points[("CMP-02", "VIS-H")]
        series = [(2.1, 6.0, 1.7), (2.2, 6.4, 1.8), (2.4, 7.1, 1.7), (2.6, 7.6, 1.9), (3.1, 9.2, 1.8), (3.6, 11.4, 1.9), (4.8, 14.2, 1.9), (6.3, 18.5, 2.0)]
        for index, (v_ca, a_ca, v_co) in enumerate(series):
            days = 3 + 14 * (len(series) - 1 - index)
            values = [(ca, P["VIB-V"], Decimal(str(v_ca))), (ca, P["VIB-A"], Decimal(str(a_ca))), (ca, P["VIB-F"], Decimal("49.6")),
                      (co, P["VIB-V"], Decimal(str(v_co))), (co, P["VIB-A"], Decimal(str(round(a_ca * 0.45, 1)))), (vis, P["VIB-V"], Decimal("2.0"))]
            record_session(equipment=eq["CMP-02"], kind="vibration", measured_at=at(days), values=values, technician=vib_tech,
                           rotation_speed=Decimal("2960"), load_condition="En charge, 7 bar",
                           observations="Composante à 1× la vitesse de rotation en hausse : suspicion de défaut de roulement." if index >= 6 else "")
            count += 1
    # EXT-01 : vibration stable, analyse d'huile mensuelle avec fer en hausse.
    if ("EXT-01", "RED-VIB") in points:
        red = points[("EXT-01", "RED-VIB")]
        for index, value in enumerate([2.1, 2.0, 2.3, 2.2, 2.1, 2.3]):
            record_session(equipment=eq["EXT-01"], kind="vibration", measured_at=at(10 + 28 * (5 - index), 10),
                           values=[(red, P["VIB-V"], Decimal(str(value)))], technician=vib_tech, rotation_speed=Decimal("1480"),
                           load_condition="Production film 450 kg/h")
            count += 1
    if oil:
        rows = [  # visc, TAN, eau, Fe, Cu, Si, ISO 4/6/14
            (221, 0.42, 120, 32, 4, 6, 17, 15, 12), (220, 0.48, 140, 36, 5, 6, 17, 15, 12), (218, 0.55, 150, 41, 5, 7, 17, 15, 12),
            (219, 0.61, 180, 47, 6, 8, 18, 15, 12), (216, 0.70, 210, 55, 7, 9, 18, 16, 13), (214, 0.78, 230, 66, 8, 11, 18, 16, 13),
            (212, 0.86, 260, 85, 9, 12, 19, 16, 13),
        ]
        codes = ["HUI-VISC", "HUI-TAN", "HUI-EAU", "HUI-FE", "HUI-CU", "HUI-SI", "ISO-4", "ISO-6", "ISO-14"]
        for index, row in enumerate(rows):
            days = 7 + 30 * (len(rows) - 1 - index)
            values = [(oil, P[code], Decimal(str(value))) for code, value in zip(codes, row, strict=True)]
            record_session(equipment=eq["EXT-01"], kind="oil", measured_at=at(days, 11), values=values, technician=oil_tech,
                           oil_type="Huile engrenages ISO VG 220", operating_hours=Decimal(str(41270 - 720 * (len(rows) - 1 - index))),
                           oil_hours=Decimal(str(1800 + 600 * index)), laboratory="Labo Analyses Industrielles",
                           lab_report_number=f"LAI-26-{1040 + index}",
                           lab_conclusion="Usure ferreuse en augmentation : surveiller, contrôler l'engrènement." if index >= 5 else "Huile en bon état.")
            count += 1
    if hyd:
        for index, value in enumerate([48, 49, 50, 51, 53, 56, 57, 58]):
            record_session(equipment=eq["PRS-INJ-03"], kind="inspection", measured_at=at(1 + 7 * (7 - index), 8),
                           values=[(hyd, P["TEMP"], Decimal(str(value)))], technician=elec_tech,
                           observations="Échangeur à contrôler (encrassement probable)." if index >= 6 else "")
            count += 1
    if gf:
        for index, value in enumerate([41.2, 42.0, 41.6, 43.1, 42.4, 44.0]):
            record_session(equipment=eq["GF-01"], kind="inspection", measured_at=at(5 + 30 * (5 - index), 14),
                           values=[(gf, P["COUR"], Decimal(str(value)))], technician=elec_tech)
            count += 1
    # Format d'import mémorisé : export CSV d'un collecteur de vibrations (une colonne par grandeur).
    ImportProfile.objects.create(name="Collecteur vibratoire (export CSV)", mapping={
        "columns": {"date": "Date/Heure", "equipment": "Machine", "point": "Point", "technician": "Opérateur", "comment": "Note"},
        "values": {"Vel RMS (mm/s)": "VIB-V", "Acc (m/s2)": "VIB-A", "Disp (um)": "VIB-D"},
    })
    return count
