"""
Démonstration en anglais (installation en anglais, ou load_demo --lang en).

Les données de démonstration sont écrites en français dans les modules « demo ». En anglais :
- le chargement se fait avec la langue anglaise active : tout texte produit par EasyMaint lui-même
  (motifs de mouvements, comptes rendus générés…) sort directement en anglais ;
- puis les textes de démonstration sont remplacés par leur traduction (DEMO_EN), champ par champ ;
- avec un autre code que « demo » (--code demo-en), les identifiants reçoivent un suffixe (« s.bensalah.en »).
"""
from contextvars import ContextVar

from django.apps import apps as django_apps
from django.db import models

_suffix = ContextVar("easymaint_demo_suffix", default="")


def set_username_suffix(suffix):
    return _suffix.set(suffix)


def demo_user(base):
    """Identifiant d'un compte de démonstration (« s.bensalah » ou « s.bensalah.en »)."""
    return f"{base}{_suffix.get()}" if base else base


DEMO_EN = {
    # Comptes, fonctions
    "Responsable maintenance": "Maintenance manager", "Ingénieure fiabilité": "Reliability engineer",
    "Chef d'équipe mécanique": "Mechanical team leader", "Technicien mécanicien": "Mechanical technician",
    "Technicienne électricienne": "Electrical technician", "Technicien hydraulicien": "Hydraulics technician",
    "Magasinière": "Storekeeper", "Chef de production": "Production manager", "Directrice d'usine": "Plant manager",
    "Administrateur": "Administrator", "Démo": "Demo", "Société de démonstration": "Demo Company",
    "Technicien de maintenance": "Maintenance technician",
    # Localisations, familles
    "Usine Ben Arous": "Ben Arous plant", "Unité Injection": "Injection unit", "Ligne 1": "Line 1", "Ligne 2": "Line 2",
    "Unité Extrusion": "Extrusion unit", "Ligne extrusion film": "Film extrusion line", "Unité Conditionnement": "Packaging unit",
    "Zone ensachage": "Bagging area", "Utilités": "Utilities", "Local compresseurs": "Compressor room",
    "Poste électrique": "Electrical substation", "Presses": "Presses", "Injection plastique": "Plastic injection",
    "Extrudeuses": "Extruders", "Compresseurs et air comprimé": "Compressors and compressed air", "Manutention": "Handling",
    "Convoyeurs": "Conveyors", "Conditionnement": "Packaging", "Thermique": "Thermal", "Refroidissement": "Cooling",
    "Électricité": "Electrical", "Hydraulique": "Hydraulics",
    # Équipements, compteurs
    "Presse à injection 220 t": "220 t injection moulding machine", "Presse à injection 350 t": "350 t injection moulding machine",
    "Presse à injection 150 t": "150 t injection moulding machine", "Heures de fonctionnement": "Operating hours",
    "Groupe hydraulique": "Hydraulic power unit", "Thermorégulateur moule": "Mould temperature controller",
    "Robot de dépose": "Take-out robot", "Sécheur de granulés": "Pellet dryer", "Extrudeuse bivis": "Twin-screw extruder",
    "Motoréducteur principal": "Main geared motor", "Calandre de refroidissement": "Cooling calender",
    "Convoyeur ligne 1": "Line 1 conveyor", "Convoyeur ligne 2": "Line 2 conveyor", "Ensacheuse verticale": "Vertical bagging machine",
    "Filmeuse de palettes": "Pallet wrapper", "Compresseur à vis 37 kW": "37 kW screw compressor",
    "Sécheur d'air frigorifique": "Refrigerated air dryer", "Groupe froid eau glacée": "Chilled water unit",
    "Tableau général basse tension": "Main low-voltage switchboard", "Transformateur 1 000 kVA": "1,000 kVA transformer",
    # Conditionnel
    "Vitesse vibratoire": "Vibration velocity", "Accélération vibratoire": "Vibration acceleration",
    "Déplacement vibratoire": "Vibration displacement", "Fréquence dominante": "Dominant frequency",
    "Viscosité à 40 °C": "Viscosity at 40 °C", "Indice d'acide (TAN)": "Acid number (TAN)", "Teneur en eau": "Water content",
    "Fer (Fe)": "Iron (Fe)", "Cuivre (Cu)": "Copper (Cu)", "Chrome (Cr)": "Chromium (Cr)", "Silicium (Si)": "Silicon (Si)",
    "Propreté ISO 4406 (> 4 µm)": "ISO 4406 cleanliness (> 4 µm)", "Propreté ISO 4406 (> 6 µm)": "ISO 4406 cleanliness (> 6 µm)",
    "Propreté ISO 4406 (> 14 µm)": "ISO 4406 cleanliness (> 14 µm)", "Température": "Temperature", "Pression": "Pressure",
    "Intensité électrique": "Electric current",
    "ISO 20816-3, groupe 2, fixation rigide (valeurs retenues par l'entreprise)":
        "ISO 20816-3, group 2, rigid mounting (values adopted by the company)",
    "Palier moteur côté accouplement": "Motor bearing, coupling side",
    "Moteur 37 kW, palier côté accouplement": "37 kW motor, coupling-side bearing",
    "Palier moteur côté opposé": "Motor bearing, non-drive side", "Moteur 37 kW, palier côté ventilateur": "37 kW motor, fan-side bearing",
    "Bloc vis": "Screw element", "Carter du bloc vis, côté refoulement": "Screw element casing, discharge side",
    "Réducteur principal, palier d'entrée": "Main gearbox, input bearing", "Réducteur X3FS, arbre d'entrée": "X3FS gearbox, input shaft",
    "Huile du réducteur principal": "Main gearbox oil", "Bouchon de prélèvement, carter du réducteur": "Sampling plug, gearbox casing",
    "Huile hydraulique": "Hydraulic oil", "Réservoir du groupe hydraulique": "Hydraulic power unit tank",
    "Compresseur frigorifique": "Refrigeration compressor", "Armoire du groupe froid, départ compresseur": "Chiller cabinet, compressor feeder",
    "Historique du parc compresseurs": "Compressor fleet history",
    "Huile ISO VG 220 : ±10 % attention, ±15 % alarme": "ISO VG 220 oil: ±10 % warning, ±15 % alarm",
    "Recommandation du laboratoire, réducteurs industriels": "Laboratory recommendation, industrial gearboxes",
    "Recommandation du laboratoire": "Laboratory recommendation", "Fiche technique de l'huile": "Oil data sheet",
    "Classe de propreté visée 18/16/13": "Target cleanliness class 18/16/13",
    "Notice Engel : huile hydraulique 35 à 55 °C": "Engel manual: hydraulic oil 35 to 55 °C",
    "Plaque moteur : 52 A nominal": "Motor nameplate: 52 A rated",
    "Vibration en alarme : demande d'intervention": "Vibration at alarm: work request",
    "Fer dans l'huile en alarme deux fois de suite : OT conditionnel": "Iron in oil at alarm twice in a row: condition-based WO",
    "En charge, 7 bar": "Loaded, 7 bar",
    "Composante à 1× la vitesse de rotation en hausse : suspicion de défaut de roulement.":
        "1× running speed component rising: suspected bearing defect.",
    "Production film 450 kg/h": "Film production 450 kg/h", "Huile engrenages ISO VG 220": "ISO VG 220 gear oil",
    "Labo Analyses Industrielles": "Industrial Analysis Lab",
    "Usure ferreuse en augmentation : surveiller, contrôler l'engrènement.": "Ferrous wear increasing: monitor, check gear meshing.",
    "Huile en bon état.": "Oil in good condition.", "Échangeur à contrôler (encrassement probable).": "Heat exchanger to check (probable fouling).",
    "Collecteur vibratoire (export CSV)": "Vibration data collector (CSV export)",
    # Finance, magasin
    "Budget de démonstration": "Demo budget", "Roulements et paliers": "Bearings and housings", "Transmission": "Power transmission",
    "Filtration": "Filtration", "Lubrifiants": "Lubricants", "Joints et étanchéité": "Seals and sealing",
    "Électricité et automatisme": "Electrical and automation", "Pneumatique": "Pneumatics",
    "Roulements et Transmissions du Sahel": "Sahel Bearings and Transmissions", "Lubrifiants Méditerranée": "Mediterranean Lubricants",
    "Électro Industrie Ben Arous": "Ben Arous Electro Industry", "Air Comprimé Services": "Compressed Air Services",
    "Roulement à billes 6205-2RS": "6205-2RS ball bearing", "Roulement à billes 6206-2RS": "6206-2RS ball bearing",
    "Roulement à billes 6310 C3 (moteur compresseur)": "6310 C3 ball bearing (compressor motor)",
    "Roulement à rotule sur rouleaux 22216 E": "22216 E spherical roller bearing", "Palier à semelle UCP205": "UCP205 pillow block bearing",
    "Courroie trapézoïdale SPZ 1250": "SPZ 1250 V-belt", "Chaîne à rouleaux simplex 08B-1": "08B-1 simplex roller chain",
    "Élastomère d'accouplement ROTEX 38 (92 Sh A)": "ROTEX 38 coupling spider (92 Sh A)",
    "Bande transporteuse PVC largeur 400 mm": "PVC conveyor belt, 400 mm wide", "Cartouche filtre retour 10 µm": "10 µm return filter cartridge",
    "Cartouche filtre pression 5 µm": "5 µm pressure filter cartridge",
    "Kit filtres GA 37 (huile + air + séparateur)": "GA 37 filter kit (oil + air + separator)",
    "Huile Roto-Inject Fluid": "Roto-Inject Fluid oil", "Graisse EP2 (cartouche 400 g)": "EP2 grease (400 g cartridge)",
    "Huile hydraulique HLP 46": "HLP 46 hydraulic oil", "Kit joints vérin de fermeture (presse 350 t)": "Clamping cylinder seal kit (350 t press)",
    'Flexible hydraulique DN12, 1 m, raccords 1/2"': 'DN12 hydraulic hose, 1 m, 1/2" fittings',
    "Coffret de joints toriques NBR (assortiment)": "NBR O-ring box (assortment)",
    "Contacteur TeSys LC1D25, bobine 230 V": "TeSys LC1D25 contactor, 230 V coil",
    "Disjoncteur moteur GV2ME14 (6-10 A)": "GV2ME14 motor circuit breaker (6-10 A)", "Détecteur inductif M18, PNP": "M18 inductive sensor, PNP",
    "Cellule photoélectrique reflex": "Retro-reflective photoelectric sensor", "Fusible cylindrique 10x38, 10 A gG": "10x38 cartridge fuse, 10 A gG",
    "Résistance chauffante collier 1 kW, Ø 60 mm": "1 kW band heater, Ø 60 mm",
    'Filtre-régulateur-lubrificateur 1/2"': '1/2" filter-regulator-lubricator',
    "Raccord instantané droit Ø 8 mm (sachet de 10)": "Ø 8 mm straight push-in fitting (bag of 10)",
    "Moteur 37 kW, paliers CA et CO": "37 kW motor, DE and NDE bearings", "Entretien 4 000 h": "4,000 h service",
    "Vidange 4 000 h": "4,000 h oil change", "Accouplement moteur / bloc vis": "Motor / screw element coupling",
    "Réducteur principal, arbre d'entrée": "Main gearbox, input shaft", "Carter du réducteur": "Gearbox casing",
    "Vérin de fermeture": "Clamping cylinder", "Filtres retour du groupe": "Power unit return filters", "Filtre pression": "Pressure filter",
    "Colliers chauffants du fourreau": "Barrel band heaters", "Détection mâchoires": "Jaw detection", "Présence sachet": "Bag presence",
    "Moteur dérouleur": "Unwinder motor", "Tambours moteur et de renvoi": "Drive and return drums", "Entraînement": "Drive",
    "Bande": "Belt", "Remplacement lors d'une ronde": "Replaced during an inspection round", "Remplacement préventif": "Preventive replacement",
    "Dépannage hors OT": "Repair outside a work order", "Consommation atelier": "Workshop consumption",
    "Magasin central": "Central store", "Magasin unité injection": "Injection unit store", "Zone industrielle, Ben Arous": "Industrial estate, Ben Arous",
    "Appoint du stock de l'unité injection": "Top-up of the injection unit stock", "Réception sur bon de commande": "Receipt against purchase order",
    "Inventaire tournant de l'unité injection": "Injection unit cycle count", "Joints du vérin de fermeture": "Clamping cylinder seals",
    "Complément après réparation": "Top-up after repair", "Rupture : commande en cours": "Out of stock: order in progress",
    "Paliers du tambour moteur": "Drive drum bearings",
    "Remplacement du capteur de pression du groupe hydraulique": "Replacement of the hydraulic power unit pressure sensor",
    "Capteur de pression 0-250 bar, sortie 4-20 mA, G1/4": "0-250 bar pressure sensor, 4-20 mA output, G1/4", "pièce": "piece",
    # Équipes, préventif
    "Équipe A · mécanique": "Team A · mechanical", "Équipe B · électricité": "Team B · electrical",
    "Contrôle hebdomadaire des sécurités": "Weekly safety check",
    "Vérifier le fonctionnement de toutes les sécurités de la presse.": "Check that all the press safety devices work.",
    "Presse à l'arrêt, moule ouvert. Ne jamais shunter une sécurité pour la tester.":
        "Press stopped, mould open. Never bypass a safety device to test it.",
    "Arrêts d'urgence (3)": "Emergency stops (3)", "Portes de protection et barrières immatérielles": "Guard doors and light curtains",
    "Clapet de sécurité hydraulique": "Hydraulic safety valve", "Voyants et alarmes": "Indicator lights and alarms",
    "Remplacement filtres hydrauliques": "Hydraulic filter replacement",
    "Remplacer les cartouches de filtration retour et pression du groupe hydraulique.":
        "Replace the return and pressure filter cartridges of the hydraulic power unit.",
    "Consigner le groupe hydraulique": "Lock out the hydraulic power unit", "Remplacer les cartouches": "Replace the cartridges",
    "Contrôler l'indicateur de colmatage": "Check the clogging indicator", "Essai et contrôle des fuites": "Test and check for leaks",
    "Remplacement filtres huile et air (4 000 h)": "Oil and air filter replacement (4,000 h)",
    "Remplacer filtre à huile, filtre à air et séparateur selon la gamme constructeur.":
        "Replace oil filter, air filter and separator according to the manufacturer's routine.",
    "Consigner et purger le compresseur": "Lock out and vent the compressor", "Remplacer filtre à huile": "Replace oil filter",
    "Remplacer filtre à air": "Replace air filter", "Contrôler le niveau d'huile": "Check the oil level", "Essai en charge": "Load test",
    "Kit filtres GA 37 (huile + air)": "GA 37 filter kit (oil + air)", "Huile Roto-Inject Fluid (L)": "Roto-Inject Fluid oil (L)",
    "Vidange réducteur principal (2 000 h)": "Main gearbox oil change (2,000 h)",
    "Vidanger le réducteur principal, remplacer l'huile et nettoyer le bouchon magnétique.":
        "Drain the main gearbox, replace the oil and clean the magnetic plug.",
    "Prélever un échantillon d'huile avant vidange": "Take an oil sample before draining", "Vidanger et rincer": "Drain and flush",
    "Nettoyer le bouchon magnétique": "Clean the magnetic plug", "Remplir et contrôler le niveau": "Refill and check the level",
    "Huile engrenages ISO VG 220 (L)": "ISO VG 220 gear oil (L)",
    "Contrôle étanchéité circuit frigorifique": "Refrigerant circuit leak check",
    "Contrôle d'étanchéité réglementaire du circuit frigorifique.": "Statutory leak check of the refrigerant circuit.",
    "Détecteur électronique sur tous les raccords": "Electronic detector on all fittings", "Relevé des pressions HP / BP": "HP / LP pressure readings",
    "Mise à jour du registre": "Update the logbook", "Nettoyage condenseur": "Condenser cleaning",
    "Nettoyer les ailettes du condenseur et contrôler les ventilateurs.": "Clean the condenser fins and check the fans.",
    "Contrôle annuel des soupapes": "Annual safety valve check",
    "Contrôle et tarage des soupapes de sécurité, révision générale annuelle.": "Check and set the safety valves, annual overhaul.",
    "Nettoyage filtres du sécheur": "Dryer filter cleaning",
    "Démonter, souffler et remonter les filtres du sécheur de granulés.": "Remove, blow out and refit the pellet dryer filters.",
    "Graissage paliers et tension de bande": "Bearing greasing and belt tension",
    "Graisser les paliers du convoyeur et contrôler la tension et l'alignement de la bande.":
        "Grease the conveyor bearings and check belt tension and alignment.",
    "Graisser les 6 paliers": "Grease the 6 bearings", "Contrôler la tension de bande": "Check the belt tension",
    "Contrôler l'alignement": "Check the alignment", "Graisse EP2 (cartouche)": "EP2 grease (cartridge)",
    "Toutes les sécurités sont opérationnelles.": "All safety devices are operational.",
    # Interventions
    "Mécanique": "Mechanical", "Automatisme": "Automation", "Soudure": "Welding", "Fuite": "Leak",
    "Bruit ou vibration anormale": "Abnormal noise or vibration", "Arrêt intempestif": "Unexpected stop", "Échauffement": "Overheating",
    "Usure normale": "Normal wear", "Joint usé ou durci": "Worn or hardened seal", "Défaut de lubrification": "Lubrication fault",
    "Capteur défaillant": "Faulty sensor", "Défaut électrique": "Electrical fault", "Mauvaise utilisation": "Misuse",
    "Remplacement de la pièce": "Part replacement", "Réglage": "Adjustment", "Nettoyage": "Cleaning",
    "Remplacement thermocouple zone 3": "Zone 3 thermocouple replacement",
    "Remplacement roulement pompe hydraulique": "Hydraulic pump bearing replacement",
    "Flexible haute pression éclaté": "Burst high-pressure hose", "Résistance de fourreau zone 2 hors service": "Zone 2 barrel heater failed",
    "Remplacement séparateur huile": "Oil separator replacement", "Bande déportée côté entraînement": "Belt drifting on the drive side",
    "Capteur présence sachet": "Bag presence sensor", "Fuite huile vérin d'éjection": "Ejector cylinder oil leak",
    "Élec": "Elec", "Électro Services Sud": "South Electro Services", "Haute tension, TGBT": "High voltage, main switchboard",
    "Rectif Mécanique": "Precision Grinding", "Rectification, usinage": "Grinding, machining",
    "Fuite d'huile sur le vérin de fermeture\nFuite importante côté plateau mobile en début de poste.":
        "Oil leak on the clamping cylinder\nMajor leak on the moving platen side at the start of the shift.",
    "Fuite d'huile sur le vérin de fermeture": "Oil leak on the clamping cylinder",
    "Consigner la presse (énergie hydraulique et électrique)": "Lock out the press (hydraulic and electrical energy)",
    "Purger la pression du circuit": "Release the circuit pressure", "Remplacer les joints du vérin": "Replace the cylinder seals",
    "Contrôler le niveau d'huile et compléter": "Check the oil level and top up",
    "Essai à vide : 10 cycles sans fuite": "No-load test: 10 cycles without leaks",
    "Le capteur de présence sachet ne détecte plus rien.": "The bag presence sensor no longer detects anything.",
    "Kit filtres GA 37 commandé": "GA 37 filter kit ordered", "Filtres nettoyés et remontés.": "Filters cleaned and refitted.",
}

# Phrases incluses dans des textes composés par la démonstration.
SUBSTRINGS = [(" : intervention réalisée, essais conformes.", ": work carried out, tests satisfactory.")]

# Colonnes à ne pas traduire : identifiants, codes, références, correspondances de colonnes d'import.
SKIP_FIELDS = {"code", "reference", "number", "username", "password", "employee_number", "serial_number", "model",
               "manufacturer_reference", "supplier_reference", "tax_id", "phone", "email", "document", "purchase_order"}


def translate_tenant(tenant):
    """Remplace, pour cette entreprise, les textes de démonstration par leur traduction anglaise."""
    from apps.accounts.models import User
    from apps.core.models import Tenant, TenantScopedModel

    changed = 0
    targets = [(model, {"tenant": tenant}) for model in django_apps.get_models() if issubclass(model, TenantScopedModel)]
    targets += [(User, {"tenant": tenant}), (Tenant, {"pk": tenant.pk})]
    for model, scope in targets:
        manager = getattr(model, "all_tenants", model._default_manager)
        fields = [f for f in model._meta.concrete_fields
                  if isinstance(f, (models.CharField, models.TextField)) and not f.choices and f.name not in SKIP_FIELDS]
        for field in fields:
            queryset = manager.filter(**scope)
            present = set(queryset.values_list(field.name, flat=True).distinct()) & DEMO_EN.keys()
            for french in present:
                english = DEMO_EN[french]
                if len(english) <= (field.max_length or 10 ** 6):
                    changed += queryset.filter(**{field.name: french}).update(**{field.name: english})
            for french, english in SUBSTRINGS:
                for obj in queryset.filter(**{f"{field.name}__contains": french}).only("pk", field.name):
                    prefix, _sep, rest = getattr(obj, field.name).partition(french)
                    value = DEMO_EN.get(prefix, prefix) + english + rest
                    changed += manager.filter(pk=obj.pk).update(**{field.name: value})
    return changed
