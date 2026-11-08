"""
Données de démonstration du magasin (appelées par `load_demo`).

Deux magasins, cinq fournisseurs, 27 articles réalistes d'une usine de plasturgie, six mois
d'entrées et de sorties (le CMP évolue avec les prix d'achat), un transfert, un inventaire
avec écart, la nomenclature de cinq équipements, et des pièces demandées sur les OT ouverts :
- presse PRS-INJ-03 (fuite vérin) : kit joints délivré, huile hydraulique en partie délivrée ;
- compresseur CMP-02 (OT préventif en attente de pièces) : kit filtres réservé par le plan, en rupture ;
- convoyeur CNV-L2 : paliers réservés ;
- plans préventifs : leurs pièces sont reliées aux articles et réservées sur les OT ouverts.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.assets.models import Equipment, Location, Manufacturer
from apps.core.demo_i18n import demo_user
from apps.workorders.models import WorkOrder

from . import services
from .models import (
    EquipmentPart,
    Item,
    ItemSupplier,
    PartFamily,
    StockCount,
    StockMovement,
    Supplier,
    Warehouse,
)

FAMILIES = [
    ("ROUL", "Roulements et paliers"), ("TRANS", "Transmission"), ("FILT", "Filtration"), ("HYD", "Hydraulique"),
    ("LUB", "Lubrifiants"), ("ETAN", "Joints et étanchéité"), ("ELEC", "Électricité et automatisme"), ("PNEU", "Pneumatique"),
]

SUPPLIERS = [
    # code, raison sociale, contact, téléphone, familles servies
    ("RTS", "Roulements et Transmissions du Sahel", "Mehdi Ferchichi", "73 000 101", ("ROUL", "TRANS")),
    ("HTD", "Hydro-Tech Distribution", "Ines Zouari", "71 000 202", ("FILT", "HYD", "ETAN")),
    ("LUBMED", "Lubrifiants Méditerranée", "Yassine Kallel", "74 000 303", ("LUB",)),
    ("EIBA", "Électro Industrie Ben Arous", "Rania Dridi", "71 000 404", ("ELEC",)),
    ("ACS", "Air Comprimé Services", "Fethi Jlassi", "71 000 505", ("PNEU",)),
]

# référence, désignation, famille, marque, fabricant, réf. constructeur, unité, prix, mini, maxi, délai (j), critique,
# magasin, quantité entrée il y a 170 j, quantité entrée il y a 60 j, quantité sortie à 120 j et à 25 j
ITEMS = [
    ("ROU-6205-2RS", "Roulement à billes 6205-2RS", "ROUL", "SKF", None, "6205-2RSH", "u", "18.500", 4, 12, 7, False, "MAG-C", 10, 6, 3),
    ("ROU-6206-2RS", "Roulement à billes 6206-2RS", "ROUL", "SKF", None, "6206-2RSH", "u", "22.800", 4, 10, 7, False, "MAG-C", 8, 0, 1),
    ("ROU-6310-C3", "Roulement à billes 6310 C3 (moteur compresseur)", "ROUL", "SKF", None, "6310/C3", "u", "96.000", 2, 4, 10, True, "MAG-C", 2, 0, 1),
    ("ROU-22216-E", "Roulement à rotule sur rouleaux 22216 E", "ROUL", "SKF", None, "22216 E", "u", "410.000", 1, 2, 21, True, "MAG-C", 2, 0, 0),
    ("ROU-UCP205", "Palier à semelle UCP205", "ROUL", "", None, "UCP205", "u", "32.000", 2, 6, 7, False, "MAG-C", 6, 2, 1),
    ("TRA-SPZ-1250", "Courroie trapézoïdale SPZ 1250", "TRANS", "Optibelt", None, "SPZ 1250 Lw", "u", "14.200", 6, 12, 7, False, "MAG-C", 12, 0, 2),
    ("TRA-CHN-08B", "Chaîne à rouleaux simplex 08B-1", "TRANS", "", None, "08B-1", "m", "9.500", 5, 20, 10, False, "MAG-C", 15, 0, 2),
    ("TRA-ROTEX-38", "Élastomère d'accouplement ROTEX 38 (92 Sh A)", "TRANS", "KTR", None, "ROTEX 38 92ShA", "u", "24.000", 2, 4, 14, False, "MAG-C", 4, 0, 1),
    ("CNV-BANDE-400", "Bande transporteuse PVC largeur 400 mm", "TRANS", "", None, "", "m", "65.000", 0, None, 20, False, "MAG-C", 12, 0, 0),
    ("PDR-HYD-0021", "Cartouche filtre retour 10 µm", "FILT", "Parker", None, "937399Q", "u", "68.000", 4, 8, 10, False, "MAG-INJ", 6, 4, 2),
    ("PDR-HYD-0022", "Cartouche filtre pression 5 µm", "FILT", "Parker", None, "G04261", "u", "112.000", 2, 4, 10, False, "MAG-INJ", 3, 2, 1),
    ("AC-2901", "Kit filtres GA 37 (huile + air + séparateur)", "FILT", "", "Atlas Copco", "2901 0526 00", "jeu", "385.000", 1, 2, 15, True, "MAG-C", 1, 0, 1),
    ("AC-ROTO", "Huile Roto-Inject Fluid", "LUB", "", "Atlas Copco", "2901 0522 00", "l", "38.500", 10, 40, 15, False, "MAG-C", 40, 0, 9),
    ("LUB-ISO220", "Huile engrenages ISO VG 220", "LUB", "", None, "", "l", "12.800", 60, 200, 7, False, "MAG-C", 200, 0, 40),
    ("LUB-EP2", "Graisse EP2 (cartouche 400 g)", "LUB", "", None, "", "u", "9.900", 10, 30, 5, False, "MAG-C", 24, 12, 6),
    ("HYD-HLP46", "Huile hydraulique HLP 46", "LUB", "", None, "", "l", "8.700", 100, 400, 7, False, "MAG-C", 400, 200, 60),
    ("HYD-KJ-VF350", "Kit joints vérin de fermeture (presse 350 t)", "ETAN", "", "Engel", "KJ-350-VF", "jeu", "640.000", 1, 2, 30, True, "MAG-INJ", 1, 0, 0),
    ("HYD-FLEX-12", "Flexible hydraulique DN12, 1 m, raccords 1/2\"", "HYD", "", None, "", "u", "45.000", 2, 6, 3, False, "MAG-INJ", 5, 0, 1),
    ("ETA-OR-KIT", "Coffret de joints toriques NBR (assortiment)", "ETAN", "", None, "", "boite", "85.000", 1, 2, 7, False, "MAG-C", 2, 0, 0),
    ("ELE-LC1D25", "Contacteur TeSys LC1D25, bobine 230 V", "ELEC", "", "Schneider Electric", "LC1D25P7", "u", "98.000", 2, 4, 5, False, "MAG-C", 4, 0, 1),
    ("ELE-GV2ME14", "Disjoncteur moteur GV2ME14 (6-10 A)", "ELEC", "", "Schneider Electric", "GV2ME14", "u", "135.000", 1, 3, 5, False, "MAG-C", 2, 0, 0),
    ("ELE-XS618", "Détecteur inductif M18, PNP", "ELEC", "", "Schneider Electric", "XS618B1PAL2", "u", "72.000", 2, 5, 7, False, "MAG-C", 3, 0, 1),
    ("ELE-XUB-REF", "Cellule photoélectrique reflex", "ELEC", "", "Schneider Electric", "XUB9BPANL2", "u", "165.000", 1, 2, 10, False, "MAG-C", 2, 0, 0),
    ("ELE-FUS-10", "Fusible cylindrique 10x38, 10 A gG", "ELEC", "", None, "", "u", "1.800", 20, 60, 3, False, "MAG-C", 60, 0, 12),
    ("THR-RES-1KW", "Résistance chauffante collier 1 kW, Ø 60 mm", "ELEC", "", "Wittmann", "", "u", "95.000", 2, 6, 15, True, "MAG-INJ", 6, 0, 1),
    ("PNE-FRL-12", "Filtre-régulateur-lubrificateur 1/2\"", "PNEU", "", None, "", "u", "210.000", 1, 2, 10, False, "MAG-C", 1, 0, 0),
    ("PNE-RAC-8", "Raccord instantané droit Ø 8 mm (sachet de 10)", "PNEU", "", None, "", "boite", "12.500", 2, 6, 5, False, "MAG-C", 5, 0, 1),
]

BOM = [
    ("CMP-02", "ROU-6310-C3", 2, "Moteur 37 kW, paliers CA et CO"), ("CMP-02", "AC-2901", 1, "Entretien 4 000 h"),
    ("CMP-02", "AC-ROTO", 18, "Vidange 4 000 h"), ("CMP-02", "TRA-ROTEX-38", 1, "Accouplement moteur / bloc vis"),
    ("EXT-01", "ROU-22216-E", 2, "Réducteur principal, arbre d'entrée"), ("EXT-01", "LUB-ISO220", 60, "Carter du réducteur"),
    ("PRS-INJ-03", "HYD-KJ-VF350", 1, "Vérin de fermeture"), ("PRS-INJ-03", "PDR-HYD-0021", 2, "Filtres retour du groupe"),
    ("PRS-INJ-03", "PDR-HYD-0022", 1, "Filtre pression"), ("PRS-INJ-03", "HYD-HLP46", 350, "Réservoir du groupe hydraulique"),
    ("PRS-INJ-03", "THR-RES-1KW", 6, "Colliers chauffants du fourreau"),
    ("ENS-04", "ELE-XS618", 2, "Détection mâchoires"), ("ENS-04", "ELE-XUB-REF", 1, "Présence sachet"), ("ENS-04", "ELE-LC1D25", 1, "Moteur dérouleur"),
    ("CNV-L2", "ROU-UCP205", 4, "Tambours moteur et de renvoi"), ("CNV-L2", "TRA-SPZ-1250", 3, "Entraînement"), ("CNV-L2", "CNV-BANDE-400", 14, "Bande"),
]

ISSUE_REASONS = ["Remplacement lors d'une ronde", "Remplacement préventif", "Dépannage hors OT", "Consommation atelier"]


def load(tenant, *, author=None):
    if Item.objects.exists():
        load_purchases(tenant, author=author)  # mise à jour d'une démonstration chargée avant la phase 5B
        return 0
    now = timezone.now()
    keeper = User.objects.filter(username=demo_user("m.saidi"), tenant=tenant).first() or author
    site = Location.objects.filter(code="BA").first()
    injection = Location.objects.filter(code="BA-INJ").first()
    warehouses = {
        "MAG-C": Warehouse.objects.create(code="MAG-C", name="Magasin central", location=site),
        "MAG-INJ": Warehouse.objects.create(code="MAG-INJ", name="Magasin unité injection", location=injection),
    }
    families = {code: PartFamily.objects.create(code=code, name=name) for code, name in FAMILIES}
    suppliers, supplier_by_family = {}, {}
    for code, name, contact, phone, served in SUPPLIERS:
        suppliers[code] = Supplier.objects.create(code=code, name=name, contact_name=contact, phone=phone,
                                                  address="Zone industrielle, Ben Arous")
        for family in served:
            supplier_by_family[family] = suppliers[code]
    manufacturers = {m.name: m for m in Manufacturer.objects.all()}

    items, events = {}, []
    for (ref, designation, family, brand, maker, mref, unit, price, min_stock, max_stock, lead, critical,
         warehouse, first, second, used) in ITEMS:
        price = Decimal(price)
        item = Item.objects.create(
            reference=ref, designation=designation, family=families[family], brand=brand, manufacturer=manufacturers.get(maker),
            manufacturer_reference=mref, unit=unit, unit_price=price, min_stock=Decimal(min_stock),
            max_stock=Decimal(max_stock) if max_stock is not None else None, lead_time_days=lead, is_critical=critical,
        )
        items[ref] = item
        supplier = suppliers["ACS"] if ref.startswith("AC-") else supplier_by_family[family]
        ItemSupplier.objects.create(item=item, supplier=supplier, supplier_reference=mref or ref, price=price,
                                    lead_time_days=lead, is_preferred=True)
        store = warehouses[warehouse]
        # Deux réceptions à prix différents : le CMP s'en trouve pondéré.
        events.append((170, "in", item, store, first, (price * Decimal("0.94")).quantize(Decimal("0.001")), supplier))
        if second:
            events.append((60, "in", item, store, second, price, supplier))
        if used:
            events.append((120, "out", item, store, used, None, None))
            if first + second - 2 * used >= 0 and second:
                events.append((25, "out", item, store, used, None, None))

    # Transfert d'huile hydraulique vers le magasin de l'unité injection.
    events.append((40, "transfer", items["HYD-HLP46"], warehouses["MAG-C"], 100, None, warehouses["MAG-INJ"]))

    for days_ago, kind, item, store, quantity, price, supplier in sorted(events, key=lambda e: -e[0]):
        moved_at = (now - timedelta(days=days_ago)).replace(hour=9 if kind == "in" else 14, minute=0, second=0, microsecond=0)
        if kind == "transfer":
            services.transfer(item=item, source=store, destination=supplier, quantity=quantity, user=keeper,
                              reason="Appoint du stock de l'unité injection", moved_at=moved_at)
        elif kind == "in":
            services.receive(item=item, warehouse=store, quantity=quantity, unit_cost=price, user=keeper, supplier=supplier,
                             document=f"BL {supplier.code}-{moved_at:%y%m}{item.pk:03d}", reason="Réception sur bon de commande",
                             purchase_order=f"ACH-{moved_at:%y%m}-{supplier.pk:02d}", moved_at=moved_at)
        else:
            equipment = next((Equipment.objects.filter(code=eq).first() for eq, ref, _q, _p in BOM if ref == item.reference), None)
            services.issue(item=item, warehouse=store, quantity=quantity, user=keeper, moved_at=moved_at, equipment=equipment,
                           reason=ISSUE_REASONS[(item.pk + days_ago) % len(ISSUE_REASONS)])

    # Inventaire du magasin injection il y a deux semaines : 2 L d'huile manquants.
    count = services.start_count(warehouse=warehouses["MAG-INJ"], user=keeper, notes="Inventaire tournant de l'unité injection")
    values = {}
    for line in count.lines.select_related("item"):
        values[line.pk] = str(line.expected - (2 if line.item.reference == "HYD-HLP46" else 0))
    services.save_counts(count, values)
    services.validate_count(count, user=keeper)
    counted_at = now - timedelta(days=14)
    StockCount.objects.filter(pk=count.pk).update(started_at=counted_at - timedelta(hours=2), validated_at=counted_at)
    StockMovement.objects.filter(count=count).update(moved_at=counted_at)

    # Nomenclature des équipements.
    equipment = {e.code: e for e in Equipment.objects.filter(code__in={code for code, *_rest in BOM})}
    for eq_code, ref, quantity, position in BOM:
        if eq_code in equipment:
            EquipmentPart.objects.create(equipment=equipment[eq_code], item=items[ref], quantity=Decimal(quantity), position=position)

    # Pièces des plans préventifs reliées au magasin, et réservées sur les OT préventifs ouverts.
    from apps.preventive.models import PlanPart, PreventivePlan

    for part in PlanPart.objects.filter(item__isnull=True):
        if part.reference in items:
            part.item = items[part.reference]
            part.save(update_fields=["item", "updated_at"])
    for wo in WorkOrder.objects.filter(status__in=WorkOrder.OPEN_STATUSES, preventive_plan__isnull=False):
        if not wo.stock_parts.exists():
            services.reserve_plan_parts(wo, PreventivePlan.objects.get(pk=wo.preventive_plan_id))

    # Pièces demandées sur les OT correctifs ouverts.
    manager = User.objects.filter(username=demo_user("s.bensalah"), tenant=tenant).first() or author
    press_order = WorkOrder.objects.filter(equipment__code="PRS-INJ-03", status=WorkOrder.Status.IN_PROGRESS).first()
    if press_order:
        technician = User.objects.filter(username=demo_user("k.trabelsi"), tenant=tenant).first() or manager
        seals = services.request_part(work_order=press_order, item=items["HYD-KJ-VF350"], quantity=1, user=technician,
                                      note="Joints du vérin de fermeture")
        services.issue_request(seals, quantity=1, user=keeper)
        oil = services.request_part(work_order=press_order, item=items["HYD-HLP46"], quantity=40, user=technician,
                                    warehouse=warehouses["MAG-INJ"], note="Complément après réparation")
        services.issue_request(oil, quantity=20, user=keeper)
    waiting = WorkOrder.objects.filter(equipment__code="CMP-02", status=WorkOrder.Status.WAITING_PARTS).first()
    if waiting and not waiting.stock_parts.filter(item=items["AC-2901"]).exists():
        services.request_part(work_order=waiting, item=items["AC-2901"], quantity=1, user=manager, note="Rupture : commande en cours")
    conveyor = WorkOrder.objects.filter(equipment__code="CNV-L2", status__in=WorkOrder.OPEN_STATUSES).first()
    if conveyor:
        services.request_part(work_order=conveyor, item=items["ROU-UCP205"], quantity=2, user=manager, note="Paliers du tambour moteur")
    load_purchases(tenant, author=author)
    return Item.objects.count()


def load_purchases(tenant, *, author=None):
    """Demandes d'achat de démonstration : réapprovisionnement et une pièce non stockée pour la presse."""
    from .models import PurchaseRequest
    from .selectors import below_minimum

    if PurchaseRequest.objects.exists() or not Item.objects.exists():
        return 0
    keeper = User.objects.filter(username=demo_user("m.saidi"), tenant=tenant).first() or author
    manager = User.objects.filter(username=demo_user("s.bensalah"), tenant=tenant).first() or author
    created = services.create_reorder_requests(list(below_minimum()), user=keeper)
    press = Equipment.objects.filter(code="PRS-INJ-03").first()
    press_order = WorkOrder.objects.filter(equipment=press, status__in=WorkOrder.OPEN_STATUSES).order_by("pk").first() if press else None
    services.save_purchase_request(
        PurchaseRequest(supplier=Supplier.objects.filter(code="HTD").first(), reason="Remplacement du capteur de pression du groupe hydraulique",
                        work_order=press_order, equipment=press, needed_by=timezone.localdate() + timedelta(days=10), is_urgent=True),
        [{"item": None, "reference": "PT-250-G14", "designation": "Capteur de pression 0-250 bar, sortie 4-20 mA, G1/4",
          "quantity": Decimal("1"), "unit": "pièce", "estimated_price": Decimal("480.000")}],
        user=manager,
    )
    return len(created) + 1
