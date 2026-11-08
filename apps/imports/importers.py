"""
Imports Excel / CSV de mise en service : équipements, articles (avec stock initial), fournisseurs,
historique de maintenance.

Principe commun : modèle à télécharger → lecture (colonnes reconnues d'après leur titre) → analyse
ligne à ligne (création, mise à jour, ignorée, refusée avec motif) → confirmation → enregistrement,
tout ou rien. La lecture des fichiers réutilise celle de l'import des mesures.
"""
import io
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone, translation
from django.utils.functional import Promise
from django.utils.translation import gettext, gettext_lazy
from django.utils.translation import gettext as _

from apps.assets.models import Equipment, EquipmentFamily, Location, Manufacturer
from apps.condition.importer import (  # noqa: F401
    _cell_text,
    normalize,
    parse_datetime_value,
    parse_number,
    read_table,
)
from apps.core.services import next_document_number

YES = {"oui", "o", "yes", "y", "1", "x", "vrai", "true"}
NO = {"non", "n", "no", "0", "faux", "false", ""}


def label_variants(label):
    """Titre de colonne normalisé dans chaque langue proposée : un fichier en français ou en anglais est reconnu."""
    variants = {normalize(str(label))}
    for code in settings.AVAILABLE_LANGUAGES:
        with translation.override(code):
            variants.add(normalize(str(label)))
    return variants


@dataclass
class Field:
    key: str
    label: str
    required: bool = False
    synonyms: tuple = ()
    example: object = ""


@dataclass
class Row:
    line: int
    action: str = ""  # create | update | skip
    data: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    label: str = ""


@dataclass
class Analysis:
    rows: list
    missing_columns: list
    total: int = 0
    truncated: bool = False

    def count(self, action):
        return sum(1 for row in self.rows if row.action == action and not row.messages)

    @property
    def errors(self):
        return [row for row in self.rows if row.messages]

    @property
    def valid(self):
        return [row for row in self.rows if not row.messages and row.action in ("create", "update")]


def yes_no(raw, default=False):
    text = normalize(_cell_text(raw))
    if text in YES:
        return True
    if text in NO:
        return default if text == "" else False
    raise ValidationError(_("« %(v)s » : répondez oui ou non.") % {"v": raw})


def text(values, key, max_length=None):
    value = _cell_text(values.get(key))
    return value[:max_length] if max_length else value


def number(values, key, *, minimum=None, maximum=None, integer=False, places=3):
    raw = values.get(key)
    if _cell_text(raw) == "":
        return None
    value = parse_number(raw)
    if value is None:
        return None
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValidationError(_("%(f)s : valeur hors limites (%(v)s).") % {"f": key, "v": _cell_text(raw)})
    if integer:
        if value != value.to_integral_value():
            raise ValidationError(_("%(f)s : nombre entier attendu.") % {"f": key})
        return int(value)
    # Arrondi au nombre de décimales du champ de destination (sinon la validation du modèle refuse la valeur).
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


class Importer:
    kind = ""
    title = ""
    description = ""
    fields: list = []
    unique_hint = ""

    def headers(self):
        return [str(f.label) for f in self.fields]

    def column_map(self, headers):
        """{clé: index de colonne} d'après les titres (libellé du modèle, clé ou synonymes)."""
        mapping = {}
        normalized = [normalize(h) for h in headers]
        for f in self.fields:
            candidates = {*label_variants(f.label), normalize(f.key), *(normalize(s) for s in f.synonyms)}
            for index, header in enumerate(normalized):
                if header in candidates and index not in mapping.values():
                    mapping[f.key] = index
                    break
        return mapping

    def analyse(self, fileobj, name, *, update_existing):
        table = read_table(fileobj, name)
        columns = self.column_map(table.headers)
        missing = [str(f.label) for f in self.fields if f.required and f.key not in columns]
        rows = []
        if not missing:
            self.prepare()
            for line, cells in table.rows:
                values = {key: (cells[index] if index < len(cells) else None) for key, index in columns.items()}
                row = Row(line=line)
                try:
                    self.check_row(row, values, update_existing=update_existing)
                except ValidationError as error:
                    row.messages.extend(error.messages)
                rows.append(row)
            self.cross_check(rows)
        return Analysis(rows=rows, missing_columns=missing, total=len(table.rows), truncated=table.truncated)

    def prepare(self):
        """Caches avant l'analyse (références existantes)."""

    def check_row(self, row, values, *, update_existing):
        raise NotImplementedError

    def cross_check(self, rows):
        """Contrôles entre lignes (doublons dans le fichier…)."""
        seen = {}
        for row in rows:
            key = row.data.get("_key")
            if not key or row.messages:
                continue
            if key in seen:
                row.messages.append(_("En double dans le fichier (ligne %(n)s).") % {"n": seen[key]})
            else:
                seen[key] = row.line

    def save_row(self, row, user):
        raise NotImplementedError

    @transaction.atomic
    def execute(self, analysis, user):
        created = updated = 0
        for row in analysis.valid:
            self.save_row(row, user)
            if row.action == "create":
                created += 1
            else:
                updated += 1
        self.after_execute(analysis, user)
        return created, updated

    def after_execute(self, analysis, user):
        pass

    def template(self):
        """Classeur modèle : feuille « Données » (titres + une ligne d'exemple) et feuille « Lisez-moi »."""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = gettext("Données")
        sheet.append(self.headers())
        sheet.append([str(f.example) if isinstance(f.example, Promise) else f.example for f in self.fields])
        for cell in sheet[1]:
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E79")
        for index, f in enumerate(self.fields):
            sheet.column_dimensions[chr(ord("A") + index) if index < 26 else "A" + chr(ord("A") + index - 26)].width = max(14, len(str(f.label)) + 4)
        sheet.freeze_panes = "A2"
        readme = workbook.create_sheet(gettext("Lisez-moi"))
        readme.append([gettext("Import EasyMaint · %(title)s") % {"title": self.title}])
        readme.append([str(self.description)])
        readme.append([str(self.unique_hint)])
        readme.append([])
        readme.append([gettext("Colonne"), gettext("Obligatoire"), gettext("Contenu")])
        for f in self.fields:
            readme.append([str(f.label), gettext("oui") if f.required else "", self.help_for(f)])
        readme.append([])
        readme.append([gettext("Supprimez la ligne d'exemple avant l'import. Les lignes vides sont ignorées."),
                       ])
        readme.append([gettext("Les titres de colonnes sont reconnus en français comme en anglais.")])
        readme.column_dimensions["A"].width, readme.column_dimensions["B"].width, readme.column_dimensions["C"].width = 28, 12, 100
        readme["A1"].font = Font(bold=True, size=13)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def help_for(self, f):
        return ""


# --- Équipements -------------------------------------------------------------------------------------

class EquipmentImporter(Importer):
    kind = "equipements"
    title = gettext_lazy("Équipements")
    description = gettext_lazy("Une ligne par équipement. La localisation (code ou nom) doit exister ; la famille et le fabricant sont créés s'ils n'existent pas.")
    unique_hint = gettext_lazy("Clé : le code de l'équipement. Un code existant est mis à jour si l'option « mettre à jour » est cochée, sinon ignoré.")
    fields = [
        Field("code", gettext_lazy("Code"), True, ("code equipement", "tag", "repere"), "CMP-03"),
        Field("designation", gettext_lazy("Désignation"), True, ("designation", "nom", "libelle"), gettext_lazy("Compresseur à vis 30 kW")),
        Field("family", gettext_lazy("Famille"), True, ("famille", "categorie", "type"), "COMP"),
        Field("location", gettext_lazy("Localisation"), True, ("localisation", "emplacement", "unite", "ligne"), "BA-UTIL"),
        Field("parent", gettext_lazy("Équipement parent"), False, ("parent",), ""),
        Field("manufacturer", gettext_lazy("Fabricant"), False, ("fabricant", "marque", "constructeur"), "Atlas Copco"),
        Field("model", gettext_lazy("Modèle"), False, ("modele", "type constructeur"), "GA 30"),
        Field("serial", gettext_lazy("N° de série"), False, ("numero de serie", "n serie", "serie"), "API123456"),
        Field("commissioning", gettext_lazy("Mise en service"), False, ("date de mise en service", "mise en service"), "15/03/2019"),
        Field("criticality", gettext_lazy("Criticité"), False, ("criticite",), "B"),
        Field("hours", gettext_lazy("Heures requises par jour"), False, ("heures requises", "heures par jour"), 16),
        Field("days", gettext_lazy("Jours par semaine"), False, ("jours de fonctionnement par semaine", "jours de fonctionnement"), 6),
        Field("notes", gettext_lazy("Notes"), False, ("observations", "commentaire"), ""),
    ]

    def help_for(self, f):
        return {
            "family": gettext("Code (ou nom) de famille ; créée si inconnue."),
            "location": gettext("Code ou nom d'une localisation existante (Localisations)."),
            "parent": gettext("Code d'un équipement existant ou présent plus haut dans le fichier."),
            "commissioning": gettext("JJ/MM/AAAA."),
            "criticality": gettext("A (critique), B (importante) ou C (secondaire) ; B par défaut."),
            "hours": gettext("0 à 24 ; 16 par défaut."),
            "days": gettext("1 à 7 (5 = lundi-vendredi, 6 = lundi-samedi) ; 6 par défaut."),
        }.get(f.key, "")

    def prepare(self):
        self.equipment = {normalize(e.code): e for e in Equipment.objects.all()}
        self.families = {}
        for family in EquipmentFamily.objects.all():
            self.families.setdefault(normalize(family.code), family)
            self.families.setdefault(normalize(family.name), family)
        self.locations = {}
        for location in Location.objects.all():
            self.locations.setdefault(normalize(location.code), location)
            self.locations.setdefault(normalize(location.name), location)
        self.file_codes = set()

    def check_row(self, row, values, *, update_existing):
        code = text(values, "code").upper()
        designation = text(values, "designation", 200)
        if not code or not designation:
            raise ValidationError(_("Code et désignation obligatoires."))
        if len(code) > 30:
            raise ValidationError(_("Code trop long (30 caractères au plus)."))
        row.label = f"{code} · {designation}"
        row.data["_key"] = normalize(code)
        existing = self.equipment.get(normalize(code))
        if existing and not update_existing:
            row.action = "skip"
            row.notes.append(_("Existe déjà : ignoré."))
            return
        row.action = "update" if existing else "create"
        family_text = text(values, "family")
        family = self.families.get(normalize(family_text))
        if not family_text:
            row.messages.append(_("Famille obligatoire."))
        elif family is None:
            row.notes.append(_("Famille « %(f)s » créée.") % {"f": family_text})
        location = self.locations.get(normalize(text(values, "location")))
        if location is None:
            row.messages.append(_("Localisation « %(l)s » inconnue : créez-la d'abord.") % {"l": text(values, "location")})
        parent_code = text(values, "parent").upper()
        if parent_code and normalize(parent_code) not in self.equipment and normalize(parent_code) not in self.file_codes:
            row.messages.append(_("Équipement parent « %(p)s » inconnu.") % {"p": parent_code})
        criticality = text(values, "criticality").upper() or "B"
        if criticality not in ("A", "B", "C"):
            row.messages.append(_("Criticité A, B ou C."))
        try:
            commissioning = parse_datetime_value(values["commissioning"]).date() if text(values, "commissioning") else None
        except ValidationError as error:
            row.messages.extend(error.messages)
            commissioning = None
        try:
            hours = number(values, "hours", minimum=0, maximum=24, places=1)
            days = number(values, "days", minimum=1, maximum=7, integer=True)
        except ValidationError as error:
            row.messages.extend(error.messages)
            hours = days = None
        self.file_codes.add(normalize(code))
        row.data.update({
            "existing": existing, "code": code, "designation": designation, "family": family, "family_text": family_text,
            "location": location, "parent_code": parent_code, "manufacturer": text(values, "manufacturer", 150),
            "model": text(values, "model", 100), "serial": text(values, "serial", 100), "commissioning": commissioning,
            "criticality": criticality, "hours": hours, "days": days, "notes": text(values, "notes"),
        })

    def save_row(self, row, user):
        d = row.data
        family = d["family"]
        if family is None:
            family = EquipmentFamily.objects.filter(code__iexact=d["family_text"][:30]).first() or EquipmentFamily.objects.create(
                code=d["family_text"][:30].upper(), name=d["family_text"][:150], created_by=user)
            self.families[normalize(d["family_text"])] = family
        manufacturer = None
        if d["manufacturer"]:
            manufacturer = Manufacturer.objects.filter(name__iexact=d["manufacturer"]).first() or Manufacturer.objects.create(
                name=d["manufacturer"], created_by=user)
        equipment = d["existing"] or Equipment(code=d["code"], created_by=user)
        equipment.designation, equipment.family, equipment.location = d["designation"], family, d["location"]
        if manufacturer is not None:
            equipment.manufacturer = manufacturer
        for attr, key in (("model", "model"), ("serial_number", "serial"), ("notes", "notes")):
            if d[key]:
                setattr(equipment, attr, d[key])
        if d["commissioning"]:
            equipment.commissioning_date = d["commissioning"]
        equipment.criticality = d["criticality"]
        if d["hours"] is not None:
            equipment.required_hours_per_day = d["hours"]
        if d["days"] is not None:
            equipment.operating_days_per_week = d["days"]
        equipment.full_clean(exclude=["parent"])
        equipment.save()
        self.equipment[normalize(d["code"])] = equipment

    def after_execute(self, analysis, user):
        for row in analysis.valid:
            if row.data["parent_code"]:
                child = self.equipment[normalize(row.data["code"])]
                parent = self.equipment.get(normalize(row.data["parent_code"]))
                if parent is not None and parent.pk != child.pk:
                    child.parent = parent
                    child.save(update_fields=["parent", "updated_at"])


# --- Fournisseurs ------------------------------------------------------------------------------------

class SupplierImporter(Importer):
    kind = "fournisseurs"
    title = gettext_lazy("Fournisseurs")
    description = gettext_lazy("Une ligne par fournisseur.")
    unique_hint = gettext_lazy("Clé : le code du fournisseur.")
    fields = [
        Field("code", gettext_lazy("Code"), True, ("code fournisseur",), "RTS"),
        Field("name", gettext_lazy("Raison sociale"), True, ("nom", "fournisseur", "societe"), gettext_lazy("Roulements et Transmissions du Sahel")),
        Field("contact", gettext_lazy("Contact"), False, ("interlocuteur",), "Mehdi Ferchichi"),
        Field("phone", gettext_lazy("Téléphone"), False, ("tel", "telephone"), "73 000 101"),
        Field("email", gettext_lazy("E-mail"), False, ("email", "mail", "courriel"), "contact@exemple.tn"),
        Field("tax_id", gettext_lazy("Matricule fiscal"), False, ("mf", "matricule"), ""),
        Field("address", gettext_lazy("Adresse"), False, (), gettext_lazy("Zone industrielle")),
        Field("notes", gettext_lazy("Notes"), False, ("observations",), ""),
    ]

    def prepare(self):
        from apps.inventory.models import Supplier

        self.suppliers = {normalize(s.code): s for s in Supplier.objects.all()}

    def check_row(self, row, values, *, update_existing):
        code, name = text(values, "code").upper(), text(values, "name", 150)
        if not code or not name:
            raise ValidationError(_("Code et raison sociale obligatoires."))
        row.label, row.data["_key"] = f"{code} · {name}", normalize(code)
        existing = self.suppliers.get(normalize(code))
        if existing and not update_existing:
            row.action = "skip"
            row.notes.append(_("Existe déjà : ignoré."))
            return
        email = text(values, "email")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                row.messages.append(_("E-mail « %(e)s » invalide.") % {"e": email})
        row.action = "update" if existing else "create"
        row.data.update({"existing": existing, "code": code[:30], "name": name, "contact_name": text(values, "contact", 150),
                         "phone": text(values, "phone", 30), "email": email, "tax_id": text(values, "tax_id", 40),
                         "address": text(values, "address"), "notes": text(values, "notes")})

    def save_row(self, row, user):
        from apps.inventory.models import Supplier

        d = row.data
        supplier = d["existing"] or Supplier(code=d["code"], created_by=user)
        supplier.name = d["name"]
        for attr in ("contact_name", "phone", "email", "tax_id", "address", "notes"):
            if d[attr]:
                setattr(supplier, attr, d[attr])
        supplier.full_clean()
        supplier.save()


# --- Articles ------------------------------------------------------------------------------------------

class ItemImporter(Importer):
    kind = "articles"
    title = gettext_lazy("Articles (pièces de rechange)")
    description = gettext_lazy("Une ligne par article. Stock initial : quantité entrée dans le magasin indiqué au prix d'achat de la ligne "
                   "(uniquement à la création de l'article). Familles et fabricants créés s'ils n'existent pas ; magasin et "
                   "fournisseur doivent exister.")
    unique_hint = gettext_lazy("Clé : la référence de l'article.")
    fields = [
        Field("reference", gettext_lazy("Référence"), True, ("ref", "code article", "article"), "ROU-6205-2RS"),
        Field("designation", gettext_lazy("Désignation"), True, ("libelle", "nom"), gettext_lazy("Roulement à billes 6205-2RS")),
        Field("family", gettext_lazy("Famille"), False, ("famille",), "ROUL"),
        Field("brand", gettext_lazy("Marque"), False, (), "SKF"),
        Field("manufacturer", gettext_lazy("Fabricant"), False, ("constructeur",), ""),
        Field("mref", gettext_lazy("Référence constructeur"), False, ("ref constructeur", "reference fabricant"), "6205-2RSH"),
        Field("unit", gettext_lazy("Unité"), False, (), gettext_lazy("pièce")),
        Field("price", gettext_lazy("Prix d'achat"), False, ("prix", "prix unitaire", "prix de reference"), 18.5),
        Field("min", gettext_lazy("Stock mini"), False, ("stock minimum", "mini"), 4),
        Field("max", gettext_lazy("Stock maxi"), False, ("stock maximum", "maxi"), 12),
        Field("lead", gettext_lazy("Délai (jours)"), False, ("delai", "delai d approvisionnement"), 7),
        Field("critical", gettext_lazy("Pièce critique"), False, ("critique",), gettext_lazy("non")),
        Field("warehouse", gettext_lazy("Magasin"), False, ("code magasin",), "MAG-C"),
        Field("stock", gettext_lazy("Stock initial"), False, ("quantite", "stock"), 10),
        Field("bin", gettext_lazy("Emplacement"), False, ("emplacement magasin", "casier"), "A-03-2"),
        Field("supplier", gettext_lazy("Fournisseur"), False, ("code fournisseur",), "RTS"),
        Field("sref", gettext_lazy("Référence fournisseur"), False, ("ref fournisseur",), ""),
    ]

    def help_for(self, f):
        return {
            "unit": gettext("pièce, jeu, paire, boîte, mètre, kilogramme, litre (ou u, m, kg, l)."),
            "critical": gettext("oui / non."),
            "warehouse": gettext("Code d'un magasin existant ; obligatoire si un stock initial est indiqué."),
            "stock": gettext("Quantité en stock au démarrage (création de l'article seulement)."),
            "supplier": gettext("Code d'un fournisseur existant (importez d'abord les fournisseurs)."),
        }.get(f.key, "")

    def prepare(self):
        from apps.inventory.models import Item, PartFamily, Supplier, Warehouse

        self.items = {normalize(i.reference): i for i in Item.objects.all()}
        self.families = {}
        for family in PartFamily.objects.all():
            self.families.setdefault(normalize(family.code), family)
            self.families.setdefault(normalize(family.name), family)
        self.warehouses = {normalize(w.code): w for w in Warehouse.objects.filter(is_active=True)}
        self.suppliers = {normalize(s.code): s for s in Supplier.objects.all()}
        self.units = {}
        for code, label in Item.Unit.choices:
            self.units[normalize(code)] = code
            for variant in label_variants(label):
                self.units[variant] = code
        self.units.update({"piece": "u", "pieces": "u", "pce": "u", "unit": "u", "units": "u", "boites": "boite", "box": "boite",
                           "metre": "m", "meter": "m", "litre": "l", "liter": "l", "kilogram": "kg", "kilogramme": "kg"})

    def check_row(self, row, values, *, update_existing):
        reference, designation = text(values, "reference").upper(), text(values, "designation", 200)
        if not reference or not designation:
            raise ValidationError(_("Référence et désignation obligatoires."))
        if len(reference) > 40:
            raise ValidationError(_("Référence trop longue (40 caractères au plus)."))
        row.label, row.data["_key"] = f"{reference} · {designation}", normalize(reference)
        existing = self.items.get(normalize(reference))
        if existing and not update_existing:
            row.action = "skip"
            row.notes.append(_("Existe déjà : ignoré."))
            return
        row.action = "update" if existing else "create"
        unit_text = text(values, "unit")
        unit = self.units.get(normalize(unit_text)) if unit_text else "u"
        if unit is None:
            row.messages.append(_("Unité « %(u)s » inconnue.") % {"u": unit_text})
        try:
            price = number(values, "price", minimum=Decimal("0"))
            minimum = number(values, "min", minimum=Decimal("0"))
            maximum = number(values, "max", minimum=Decimal("0"))
            lead = number(values, "lead", minimum=0, maximum=3650, integer=True)
            stock = number(values, "stock", minimum=Decimal("0"))
            critical = yes_no(values.get("critical"))
        except ValidationError as error:
            row.messages.extend(error.messages)
            price = minimum = maximum = lead = stock = None
            critical = False
        if minimum is not None and maximum is not None and maximum < minimum:
            row.messages.append(_("Stock maxi inférieur au mini."))
        warehouse = self.warehouses.get(normalize(text(values, "warehouse"))) if text(values, "warehouse") else None
        if text(values, "warehouse") and warehouse is None:
            row.messages.append(_("Magasin « %(m)s » inconnu.") % {"m": text(values, "warehouse")})
        if stock and warehouse is None and not text(values, "warehouse"):
            row.messages.append(_("Indiquez le magasin du stock initial."))
        if stock and existing:
            row.notes.append(_("Article existant : stock initial ignoré (faites un ajustement ou un inventaire)."))
            stock = None
        supplier = self.suppliers.get(normalize(text(values, "supplier"))) if text(values, "supplier") else None
        if text(values, "supplier") and supplier is None:
            row.messages.append(_("Fournisseur « %(f)s » inconnu.") % {"f": text(values, "supplier")})
        family_text = text(values, "family")
        if family_text and normalize(family_text) not in self.families:
            row.notes.append(_("Famille « %(f)s » créée.") % {"f": family_text})
        row.data.update({
            "existing": existing, "reference": reference, "designation": designation, "family_text": family_text,
            "brand": text(values, "brand", 100), "manufacturer": text(values, "manufacturer", 150), "mref": text(values, "mref", 80),
            "unit": unit, "price": price, "min": minimum, "max": maximum, "lead": lead, "critical": critical,
            "warehouse": warehouse, "stock": stock, "bin": text(values, "bin", 60), "supplier": supplier, "sref": text(values, "sref", 80),
        })

    def save_row(self, row, user):
        from apps.inventory import services
        from apps.inventory.models import Item, ItemSupplier, PartFamily, StockLevel

        d = row.data
        family = None
        if d["family_text"]:
            family = self.families.get(normalize(d["family_text"]))
            if family is None:
                family = PartFamily.objects.create(code=d["family_text"][:20].upper(), name=d["family_text"][:120], created_by=user)
                self.families[normalize(d["family_text"])] = family
        manufacturer = None
        if d["manufacturer"]:
            manufacturer = Manufacturer.objects.filter(name__iexact=d["manufacturer"]).first() or Manufacturer.objects.create(
                name=d["manufacturer"], created_by=user)
        item = d["existing"] or Item(reference=d["reference"], created_by=user)
        item.designation, item.unit, item.is_critical = d["designation"], d["unit"], d["critical"]
        if family is not None:
            item.family = family
        if manufacturer is not None:
            item.manufacturer = manufacturer
        for attr, key in (("brand", "brand"), ("manufacturer_reference", "mref")):
            if d[key]:
                setattr(item, attr, d[key])
        for attr, key in (("unit_price", "price"), ("min_stock", "min"), ("max_stock", "max"), ("lead_time_days", "lead")):
            if d[key] is not None:
                setattr(item, attr, d[key])
        item.full_clean()
        item.save()
        self.items[normalize(d["reference"])] = item
        if d["supplier"] is not None:
            link, _created = ItemSupplier.objects.get_or_create(
                item=item, supplier=d["supplier"],
                defaults={"created_by": user, "is_preferred": not item.suppliers.filter(is_preferred=True).exists()})
            link.supplier_reference = d["sref"] or link.supplier_reference
            if d["price"] is not None:
                link.price = d["price"]
            link.lead_time_days = d["lead"] if d["lead"] is not None else link.lead_time_days
            link.save()
        if d["warehouse"] is not None and d["bin"]:
            level, _created = StockLevel.objects.get_or_create(item=item, warehouse=d["warehouse"])
            level.bin_location = d["bin"]
            level.save(update_fields=["bin_location", "updated_at"])
        if d["stock"]:
            services.receive(item=item, warehouse=d["warehouse"], quantity=d["stock"], unit_cost=d["price"] or 0, user=user,
                             reason=_("Stock initial (import)"), supplier=None)


# --- Historique de maintenance ------------------------------------------------------------------------

class HistoryImporter(Importer):
    kind = "historique"
    title = gettext_lazy("Historique de maintenance")
    description = gettext_lazy("Une ligne par intervention passée. Chaque ligne crée un OT validé (coûts figés) daté de ses dates réelles, "
                   "et un arrêt machine si « Arrêt de production » vaut oui : MTBF, MTTR, disponibilité et coûts tiennent "
                   "compte du passé.")
    unique_hint = gettext_lazy("Une intervention déjà présente (même équipement, même début, même intitulé) est ignorée.")
    fields = [
        Field("start", gettext_lazy("Début"), True, ("date debut", "date", "debut intervention"), "12/01/2025 08:00"),
        Field("end", gettext_lazy("Fin"), True, ("date fin", "fin intervention"), "12/01/2025 11:30"),
        Field("equipment", gettext_lazy("Équipement"), True, ("code equipement", "machine"), "PRS-INJ-03"),
        Field("kind", gettext_lazy("Type"), True, ("type de maintenance", "nature"), gettext_lazy("correctif")),
        Field("title", gettext_lazy("Intitulé"), True, ("objet", "libelle", "titre"), gettext_lazy("Fuite d'huile vérin de fermeture")),
        Field("work_done", gettext_lazy("Travaux réalisés"), False, ("travaux", "compte rendu"), gettext_lazy("Remplacement du kit joints")),
        Field("cause", gettext_lazy("Cause / diagnostic"), False, ("cause", "diagnostic"), gettext_lazy("Usure des joints")),
        Field("stopped", gettext_lazy("Arrêt de production"), False, ("arret", "arret production"), gettext_lazy("oui")),
        Field("downtime", gettext_lazy("Durée d'arrêt (h)"), False, ("duree arret", "duree d arret"), 4.5),
        Field("labour", gettext_lazy("Main-d'œuvre"), False, ("main d oeuvre", "cout main d oeuvre", "mo"), 120),
        Field("parts", gettext_lazy("Pièces"), False, ("cout pieces", "pieces"), 640),
        Field("external", gettext_lazy("Prestations externes"), False, ("prestations", "sous traitance"), ""),
        Field("other", gettext_lazy("Autres dépenses"), False, ("autres",), ""),
    ]
    KINDS = {"correctif": "corrective", "curatif": "corrective", "depannage": "corrective", "corrective": "corrective",
             "preventif": "preventive", "preventive": "preventive", "systematique": "preventive",
             "conditionnel": "conditional", "predictif": "conditional", "conditional": "conditional",
             "amelioratif": "improvement", "amelioration": "improvement", "improvement": "improvement",
             "breakdown": "corrective", "repair": "corrective", "predictive": "conditional", "condition based": "conditional"}

    def help_for(self, f):
        return {
            "start": gettext("JJ/MM/AAAA HH:MM (dans le passé)."), "end": gettext("Après le début."),
            "kind": gettext("correctif, préventif, conditionnel ou amélioratif."),
            "stopped": gettext("oui / non : crée un arrêt machine (pris en compte dans la disponibilité)."),
            "downtime": gettext("Durée de l'arrêt en heures ; à défaut, du début à la fin."),
            "labour": gettext("Montants HT dans la devise de l'entreprise."),
        }.get(f.key, "")

    def prepare(self):
        from apps.workorders.models import WorkOrder

        self.equipment = {normalize(e.code): e for e in Equipment.objects.all()}
        self.known = set(WorkOrder.objects.filter(started_at__isnull=False).values_list("equipment_id", "started_at", "title"))

    def check_row(self, row, values, *, update_existing):
        equipment = self.equipment.get(normalize(text(values, "equipment")))
        title = text(values, "title", 200)
        row.label = f"{text(values, 'equipment')} · {title}"
        if equipment is None:
            row.messages.append(_("Équipement « %(e)s » inconnu.") % {"e": text(values, "equipment")})
        if not title:
            row.messages.append(_("Intitulé obligatoire."))
        kind = self.KINDS.get(normalize(text(values, "kind")))
        if kind is None:
            row.messages.append(_("Type « %(t)s » inconnu (correctif, préventif, conditionnel, amélioratif).") % {"t": text(values, "kind")})
        start = end = None
        try:
            start, end = parse_datetime_value(values.get("start")), parse_datetime_value(values.get("end"))
            if end < start:
                row.messages.append(_("La fin précède le début."))
        except ValidationError as error:
            row.messages.extend(error.messages)
        try:
            stopped = yes_no(values.get("stopped"))
            downtime = number(values, "downtime", minimum=Decimal("0"), maximum=Decimal("10000"))
            costs = {key: number(values, key, minimum=Decimal("0")) or Decimal("0") for key in ("labour", "parts", "external", "other")}
        except ValidationError as error:
            row.messages.extend(error.messages)
            stopped, downtime, costs = False, None, {}
        if row.messages:
            return
        row.data.update({"_key": (equipment.pk, start, title), "equipment": equipment, "title": title, "kind": kind,
                         "start": start, "end": end, "work_done": text(values, "work_done"), "cause": text(values, "cause"),
                         "stopped": stopped, "downtime": downtime, **costs})
        if (equipment.pk, start, title) in self.known:
            row.action = "skip"
            row.notes.append(_("Déjà importée : ignorée."))
        else:
            row.action = "create"

    def save_row(self, row, user):
        from apps.workorders.models import Downtime, WorkOrder

        d = row.data
        total = d["labour"] + d["parts"] + d["external"] + d["other"]
        wo = WorkOrder.objects.create(
            number=next_document_number("OT", year=timezone.localtime(d["start"]).year), kind=d["kind"], equipment=d["equipment"],
            title=d["title"], description=_("Historique importé."), status=WorkOrder.Status.VALIDATED,
            production_stopped=d["stopped"], started_at=d["start"], finished_at=d["end"], validated_at=d["end"],
            work_done=d["work_done"], diagnosis=d["cause"], labour_cost=d["labour"], parts_cost=d["parts"],
            external_cost=d["external"], other_cost=d["other"], total_cost=total, created_by=user,
        )
        WorkOrder.objects.filter(pk=wo.pk).update(created_at=d["start"])
        if d["stopped"]:
            end = d["start"] + timedelta(hours=float(d["downtime"])) if d["downtime"] is not None else d["end"]
            Downtime.objects.create(
                equipment=d["equipment"], work_order=wo, started_at=d["start"], ended_at=end, production_stopped=True,
                origin=Downtime.Origin.FAILURE if d["kind"] == "corrective" else Downtime.Origin.PREVENTIVE, created_by=user,
            )


IMPORTERS = {cls.kind: cls for cls in (EquipmentImporter, SupplierImporter, ItemImporter, HistoryImporter)}
ORDER = ["equipements", "fournisseurs", "articles", "historique"]
