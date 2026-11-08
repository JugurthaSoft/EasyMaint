"""
Import de mesures depuis un fichier CSV ou Excel (export d'appareil, de collecteur ou de laboratoire).

Deux dispositions sont reconnues, éventuellement combinées :

- **format long** : une mesure par ligne (colonnes Date, Équipement, Point, Paramètre, Valeur…) ;
- **format large** : une ligne par point et par date, une colonne par paramètre
  (« VIB-V », « Température (°C) »…).

La correspondance entre colonnes et champs (`mapping`) a la forme :

    {"columns": {"date": "Horodatage", "point": "Point", ...},
     "values": {"Vitesse V": "VIB-V", "Temp": "TEMP"}}

Les mesures sont enregistrées par `services.record_session`, exactement comme une saisie
manuelle : niveaux, alertes et règles de déclenchement s'appliquent. Une mesure déjà connue
(même point, même paramètre, même date) est ignorée.
"""
import csv
import io
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy
from django.utils.translation import gettext as _

from apps.assets.models import Equipment
from apps.workforce.models import Technician

from . import services
from .models import (
    Measurement,
    MeasurementImport,
    MeasurementPoint,
    MeasurementSession,
    Parameter,
)

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_MEASUREMENTS = 20000
MAX_STORED_ERRORS = 500
ALLOWED_EXTENSIONS = (".csv", ".txt", ".xlsx", ".xlsm")
VALUE_LIMIT = Decimal("10000000000")  # 10 chiffres avant la virgule, 4 après (Measurement.value)

# (code, libellé, obligatoire)
FIELDS = [
    ("date", gettext_lazy("Date et heure"), True),
    ("equipment", gettext_lazy("Équipement (code)"), False),
    ("point", gettext_lazy("Point de mesure (code)"), True),
    ("parameter", gettext_lazy("Paramètre (code)"), False),
    ("value", gettext_lazy("Valeur"), False),
    ("technician", gettext_lazy("Technicien (matricule)"), False),
    ("kind", gettext_lazy("Type de mesure"), False),
    ("comment", gettext_lazy("Commentaire"), False),
]
FIELD_CODES = [code for code, _label, _required in FIELDS]

SYNONYMS = {
    "date": ["date", "date heure", "date et heure", "date mesure", "date de mesure", "horodatage", "timestamp",
             "datetime", "time", "heure", "date time", "measured at", "date prelevement", "date de prelevement"],
    "equipment": ["equipement", "code equipement", "equipment", "machine", "asset", "tag", "code machine", "equipment code"],
    "point": ["point", "point de mesure", "code point", "measurement point", "mesure point", "point code"],
    "parameter": ["parametre", "code parametre", "parameter", "grandeur", "indicateur", "parameter code"],
    "value": ["valeur", "value", "resultat", "result", "mesure", "valeur mesuree"],
    "technician": ["technicien", "matricule", "operateur", "technician", "operator"],
    "kind": ["type", "type de mesure", "kind", "nature"],
    "comment": ["commentaire", "commentaires", "observation", "observations", "remarque", "remarques", "comment"],
}

KIND_SYNONYMS = {
    MeasurementSession.Kind.VIBRATION: ["vibration", "vibratoire", "analyse vibratoire", "vib", "vibration analysis"],
    MeasurementSession.Kind.OIL: ["huile", "oil", "analyse d huile", "analyse huile", "lubrifiant", "oil analysis", "lubricant"],
    MeasurementSession.Kind.INSPECTION: ["inspection", "releve", "controle", "controle releve", "ronde", "mesure",
                                         "check", "reading", "condition check", "check reading", "round"],
}

DATE_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d/%m/%y %H:%M", "%d/%m/%y",
]


def normalize(text):
    """« Équipement (code) » → « equipement code » : comparaison sans accents ni ponctuation."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# ---------------------------------------------------------------------------
# Lecture des fichiers
# ---------------------------------------------------------------------------

@dataclass
class Table:
    headers: list
    rows: list  # liste de (numéro de ligne dans le fichier, [cellules])
    truncated: bool = False


def check_upload(uploaded):
    ext = os.path.splitext(uploaded.name)[1].lower()
    if ext == ".xls":
        raise ValidationError(_("L'ancien format Excel .xls n'est pas pris en charge : enregistrez le fichier en .xlsx ou en CSV."))
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(_("Format non pris en charge : fichiers CSV ou Excel (.xlsx) uniquement."))
    if uploaded.size > MAX_FILE_SIZE:
        raise ValidationError(_("Le fichier dépasse %(n)s Mo.") % {"n": MAX_FILE_SIZE // (1024 * 1024)})


def read_table(fileobj, name):
    """Lit la première feuille (ou la feuille « Mesures ») d'un classeur, ou un CSV. Lève ValidationError."""
    ext = os.path.splitext(name)[1].lower()
    raw_rows = _read_xlsx(fileobj) if ext in (".xlsx", ".xlsm") else _read_csv(fileobj)
    headers, rows, header_line = None, [], 0
    truncated = False
    for line, cells in raw_rows:
        if headers is None:
            if any(_cell_text(c) for c in cells):
                headers, header_line = [_cell_text(c) for c in cells], line
            continue
        if not any(_cell_text(c) for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append((line, list(cells)))
    if headers is None:
        raise ValidationError(_("Le fichier est vide."))
    while headers and not headers[-1]:  # colonnes vides en fin de feuille Excel
        headers.pop()
    # Colonnes sans titre : nommées d'après leur position pour rester sélectionnables.
    seen = {}
    for index, header in enumerate(headers):
        header = header or _("Colonne %(n)s") % {"n": index + 1}
        if header in seen:
            seen[header] += 1
            header = f"{header} ({seen[header]})"
        else:
            seen[header] = 1
        headers[index] = header
    if not rows:
        raise ValidationError(_("Le fichier ne contient aucune ligne de données sous la ligne de titres (ligne %(n)s).") % {"n": header_line})
    return Table(headers=headers, rows=rows, truncated=truncated)


def _read_xlsx(fileobj):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception as exc:  # fichier corrompu ou non Excel
        raise ValidationError(_("Fichier Excel illisible (%(e)s).") % {"e": exc.__class__.__name__}) from exc
    try:
        named = [title for title in ("Mesures", "Measurements") if title in workbook.sheetnames]
        sheet = workbook[named[0]] if named else workbook.worksheets[0]
        rows = [(index, list(cells)) for index, cells in enumerate(sheet.iter_rows(values_only=True), start=1)]
    finally:
        workbook.close()
    return rows


def _read_csv(fileobj):
    data = fileobj.read()
    if isinstance(data, str):
        text = data
    else:
        text = None
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("latin-1")
    # Séparateur : le plus fréquent sur la ligne de titres (« ; » en cas d'égalité, usage français).
    header = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(";,\t|", key=lambda candidate: (header.count(candidate), candidate == ";"))
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [(index, row) for index, row in enumerate(reader, start=1)]


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


# ---------------------------------------------------------------------------
# Correspondance des colonnes
# ---------------------------------------------------------------------------

def guess_mapping(headers, parameters=None):
    """Propose une correspondance d'après les titres de colonnes et les paramètres de l'entreprise."""
    parameters = list(Parameter.objects.all() if parameters is None else parameters)
    by_name = {}
    for parameter in parameters:
        for key in (parameter.code, parameter.name, str(parameter)):
            by_name.setdefault(normalize(key), parameter.code)
    columns, values = {}, {}
    for header in headers:
        key = normalize(header)
        target = next((code for code, words in SYNONYMS.items() if key in words and code not in columns), None)
        if target:
            columns[target] = header
        elif key in by_name:
            values[header] = by_name[key]
    return {"columns": columns, "values": values}


def clean_mapping(mapping, headers):
    """Ne garde que les colonnes présentes dans le fichier (utile pour appliquer un format mémorisé)."""
    mapping = mapping or {}
    headers = set(headers)
    columns = {k: v for k, v in (mapping.get("columns") or {}).items() if k in FIELD_CODES and v in headers}
    used = set(columns.values())
    values = {k: v for k, v in (mapping.get("values") or {}).items() if k in headers and k not in used and v}
    return {"columns": columns, "values": values}


def mapping_problems(mapping):
    """Ce qui manque pour pouvoir lire le fichier (liste vide si la correspondance est utilisable)."""
    columns = mapping.get("columns", {})
    problems = []
    if "date" not in columns:
        problems.append(_("Indiquez la colonne de la date."))
    if "point" not in columns:
        problems.append(_("Indiquez la colonne du point de mesure."))
    long_format = "parameter" in columns or "value" in columns
    if long_format and not ("parameter" in columns and "value" in columns):
        problems.append(_("En format « une mesure par ligne », indiquez à la fois la colonne du paramètre et celle de la valeur."))
    if not long_format and not mapping.get("values"):
        problems.append(_("Indiquez les colonnes de valeurs : soit les colonnes Paramètre et Valeur, soit une colonne par paramètre."))
    return problems


# ---------------------------------------------------------------------------
# Résolution des références (partagée avec l'API)
# ---------------------------------------------------------------------------

class Resolver:
    """Retrouve équipements, points, paramètres et techniciens de l'entreprise courante, avec cache."""

    def __init__(self):
        self.equipment = {normalize(e.code): e for e in Equipment.objects.all()}
        self.parameters = {normalize(p.code): p for p in Parameter.objects.all()}
        self.technicians = {normalize(t.employee_number): t for t in Technician.objects.all()}
        self.points = {}
        self.points_by_code = {}
        self.point_parameters = {}
        points = MeasurementPoint.objects.select_related("equipment").prefetch_related("parameters")
        for point in points:
            self.points[(point.equipment_id, normalize(point.code))] = point
            self.points_by_code.setdefault(normalize(point.code), []).append(point)
            self.point_parameters[point.pk] = {p.pk for p in point.parameters.all()}

    def find_equipment(self, code):
        equipment = self.equipment.get(normalize(code))
        if equipment is None:
            raise ValidationError(_("Équipement « %(c)s » inconnu.") % {"c": code})
        return equipment

    def find_point(self, code, equipment=None):
        if equipment is not None:
            point = self.points.get((equipment.pk, normalize(code)))
            if point is None:
                raise ValidationError(_("Point « %(p)s » inconnu sur l'équipement %(e)s.") % {"p": code, "e": equipment.code})
            return point
        candidates = self.points_by_code.get(normalize(code), [])
        if not candidates:
            raise ValidationError(_("Point « %(p)s » inconnu.") % {"p": code})
        if len(candidates) > 1:
            raise ValidationError(_("Le code de point « %(p)s » existe sur plusieurs équipements : ajoutez la colonne Équipement.") % {"p": code})
        return candidates[0]

    def find_parameter(self, code, point):
        parameter = self.parameters.get(normalize(code))
        if parameter is None:
            raise ValidationError(_("Paramètre « %(c)s » inconnu.") % {"c": code})
        if parameter.pk not in self.point_parameters.get(point.pk, set()):
            raise ValidationError(_("Le paramètre %(c)s n'est pas mesuré sur le point %(p)s.") % {"c": parameter.code, "p": point.code})
        return parameter

    def find_technician(self, number):
        technician = self.technicians.get(normalize(number))
        if technician is None:
            raise ValidationError(_("Matricule « %(m)s » inconnu.") % {"m": number})
        return technician


def parse_kind(raw):
    key = normalize(raw)
    for kind, words in KIND_SYNONYMS.items():
        if key == normalize(kind) or key in words:
            return kind
    raise ValidationError(_("Type de mesure « %(t)s » inconnu (vibration, huile ou relevé).") % {"t": raw})


def kind_for(parameters):
    """Type de tournée déduit des paramètres : vibratoire ou huile s'ils le sont tous, sinon relevé."""
    categories = {p.category for p in parameters}
    if categories == {Parameter.Category.VIBRATION}:
        return MeasurementSession.Kind.VIBRATION
    if categories == {Parameter.Category.OIL}:
        return MeasurementSession.Kind.OIL
    return MeasurementSession.Kind.INSPECTION


def parse_datetime_value(raw):
    """Date d'une cellule (datetime Excel, texte JJ/MM/AAAA HH:MM, ISO 8601…) → datetime aware."""
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, date):
        value = datetime.combine(raw, time.min)
    else:
        text = _cell_text(raw)
        if not text:
            raise ValidationError(_("Date manquante."))
        value = None
        for fmt in DATE_FORMATS:
            try:
                value = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if value is None:
            try:
                value = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                raise ValidationError(_("Date « %(d)s » illisible (attendu JJ/MM/AAAA HH:MM).") % {"d": text}) from None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    value = value.replace(microsecond=0)
    if value > timezone.now() + timedelta(minutes=5):
        raise ValidationError(_("Date %(d)s dans le futur.") % {"d": timezone.localtime(value).strftime("%d/%m/%Y %H:%M")})
    return value


def parse_number(raw):
    """Valeur d'une cellule → Decimal à 4 décimales ; vide → None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValidationError(_("« %(v)s » n'est pas un nombre.") % {"v": raw})
    if isinstance(raw, (int, float, Decimal)):
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            raise ValidationError(_("« %(v)s » n'est pas un nombre.") % {"v": raw}) from None
    else:
        value = services.parse_value(str(raw))
        if value is None:
            return None
    if not value.is_finite() or abs(value) >= VALUE_LIMIT:
        raise ValidationError(_("Valeur %(v)s hors limites.") % {"v": raw})
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Analyse ligne à ligne
# ---------------------------------------------------------------------------

@dataclass
class Item:
    line: int
    equipment: object
    point: object
    parameter: object
    value: Decimal
    measured_at: datetime
    technician: object = None
    kind: str = ""
    comment: str = ""
    duplicate: bool = False


@dataclass
class Analysis:
    total_rows: int = 0
    items: list = field(default_factory=list)  # mesures valides, doublons compris (duplicate=True)
    errors: list = field(default_factory=list)  # [{"line": n, "messages": [...]}]
    truncated: bool = False

    @property
    def new_items(self):
        return [item for item in self.items if not item.duplicate]

    @property
    def duplicates(self):
        return sum(1 for item in self.items if item.duplicate)

    @property
    def sessions(self):
        return len(group_items(self.new_items))

    @property
    def rejected(self):
        return len(self.errors)


def analyse_table(table, mapping, resolver=None):
    resolver = resolver or Resolver()
    columns = mapping.get("columns", {})
    index = {header: position for position, header in enumerate(table.headers)}
    col = {name: index[header] for name, header in columns.items() if header in index}
    value_cols = [(index[header], header, code) for header, code in (mapping.get("values") or {}).items() if header in index]
    analysis = Analysis(total_rows=len(table.rows), truncated=table.truncated)
    seen = set()

    def cell(cells, name):
        position = col.get(name)
        return cells[position] if position is not None and position < len(cells) else None

    for line, cells in table.rows:
        messages, row_items = [], []
        try:
            measured_at = parse_datetime_value(cell(cells, "date"))
        except ValidationError as exc:
            messages.extend(exc.messages)
            measured_at = None
        equipment = point = technician = None
        kind = ""
        try:
            if _cell_text(cell(cells, "equipment")):
                equipment = resolver.find_equipment(_cell_text(cell(cells, "equipment")))
            point_code = _cell_text(cell(cells, "point"))
            if not point_code:
                raise ValidationError(_("Point de mesure manquant."))
            point = resolver.find_point(point_code, equipment)
            equipment = point.equipment
        except ValidationError as exc:
            messages.extend(exc.messages)
        for name, finder in (("technician", resolver.find_technician), ("kind", parse_kind)):
            text = _cell_text(cell(cells, name))
            if text:
                try:
                    if name == "technician":
                        technician = finder(text)
                    else:
                        kind = finder(text)
                except ValidationError as exc:
                    messages.extend(exc.messages)
        comment = _cell_text(cell(cells, "comment"))[:500]

        pairs = []  # (code paramètre, valeur brute, titre de colonne)
        if "parameter" in col:
            code = _cell_text(cell(cells, "parameter"))
            raw = cell(cells, "value")
            if not code:
                messages.append(_("Paramètre manquant."))
            elif _cell_text(raw) == "":
                messages.append(_("Valeur manquante."))
            else:
                pairs.append((code, raw, None))
        for position, header, code in value_cols:
            raw = cells[position] if position < len(cells) else None
            if _cell_text(raw) != "":
                pairs.append((code, raw, header))
        if not pairs and "parameter" not in col:
            messages.append(_("Aucune valeur sur cette ligne."))

        if point is not None:
            for code, raw, header in pairs:
                prefix = f"{header} : " if header else ""
                try:
                    parameter = resolver.find_parameter(code, point)
                    value = parse_number(raw)
                except ValidationError as exc:
                    messages.extend(prefix + message for message in exc.messages)
                    continue
                if value is not None and measured_at is not None:
                    row_items.append(Item(line=line, equipment=equipment, point=point, parameter=parameter, value=value,
                                          measured_at=measured_at, technician=technician, kind=kind, comment=comment))
        if messages:
            analysis.errors.append({"line": line, "messages": messages})
            continue
        for item in row_items:
            key = (item.point.pk, item.parameter.pk, item.measured_at)
            item.duplicate = key in seen
            seen.add(key)
            analysis.items.append(item)

    _flag_existing(analysis.items)
    return analysis


def _flag_existing(items):
    """Marque les mesures déjà présentes en base (même point, même paramètre, même date)."""
    candidates = [item for item in items if not item.duplicate]
    if not candidates:
        return
    start = min(item.measured_at for item in candidates)
    end = max(item.measured_at for item in candidates)
    existing = set(
        Measurement.objects.filter(
            point_id__in={item.point.pk for item in candidates}, measured_at__gte=start, measured_at__lte=end,
        ).values_list("point_id", "parameter_id", "measured_at")
    )
    for item in candidates:
        if (item.point.pk, item.parameter.pk, item.measured_at) in existing:
            item.duplicate = True


def group_items(items):
    """Regroupe les mesures en tournées : même équipement, même type, même date, même technicien."""
    groups = {}
    for item in items:
        kind = item.kind or kind_for([item.parameter])
        key = (item.equipment.pk, kind, item.measured_at, getattr(item.technician, "pk", None))
        groups.setdefault(key, []).append(item)
    return dict(sorted(groups.items(), key=lambda entry: (entry[0][2], entry[0][0])))


def analyse(imp, mapping=None):
    """Relit le fichier conservé de l'import et l'analyse avec la correspondance donnée (ou la sienne)."""
    with imp.file.open("rb") as handle:
        table = read_table(handle, imp.original_name)
    return table, analyse_table(table, mapping if mapping is not None else imp.mapping)


def store_analysis(imp, analysis):
    """Mémorise le bilan de l'analyse sur l'import (aperçu et historique)."""
    imp.total_rows = analysis.total_rows
    imp.skipped = analysis.duplicates
    imp.rejected = analysis.rejected
    imp.errors = analysis.errors[:MAX_STORED_ERRORS]
    imp.save(update_fields=["total_rows", "skipped", "rejected", "errors", "updated_at"])


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------

def execute(imp, *, user):
    """
    Enregistre les mesures valides et nouvelles de l'import, tournée par tournée, dans l'ordre
    chronologique (pour que les alertes suivent l'évolution réelle). Tout ou rien.
    Les lignes en erreur sont ignorées et restent listées dans le bilan.
    """
    with transaction.atomic():
        imp = MeasurementImport.objects.select_for_update().get(pk=imp.pk)
        if imp.status != MeasurementImport.Status.DRAFT:
            raise ValidationError(_("Cet import a déjà été traité."))
        problems = mapping_problems(imp.mapping)
        if problems:
            raise ValidationError(problems)
        _table, analysis = analyse(imp)
        new_items = analysis.new_items
        if not new_items:
            raise ValidationError(_("Aucune mesure nouvelle à importer."))
        if len(new_items) > MAX_MEASUREMENTS:
            raise ValidationError(_("Trop de mesures dans un seul import (%(n)s au maximum) : découpez le fichier.") % {"n": MAX_MEASUREMENTS})
        groups = group_items(new_items)
        for (_equipment_pk, kind, measured_at, _tech), items in groups.items():
            comments = list(dict.fromkeys(item.comment for item in items if item.comment))
            observations = "\n".join([_("Importé depuis %(f)s.") % {"f": imp.original_name}] + comments)
            services.record_session(
                equipment=items[0].equipment, kind=kind, measured_at=measured_at, user=user,
                technician=items[0].technician, observations=observations, source_import=imp,
                values=[(item.point, item.parameter, item.value) for item in items],
            )
        imp.total_rows = analysis.total_rows
        imp.imported = len(new_items)
        imp.skipped = analysis.duplicates
        imp.rejected = analysis.rejected
        imp.errors = analysis.errors[:MAX_STORED_ERRORS]
        imp.sessions_created = len(groups)
        imp.status = MeasurementImport.Status.DONE
        imp.imported_at = timezone.now()
        imp.save()
    return imp


# ---------------------------------------------------------------------------
# Modèle de fichier à télécharger
# ---------------------------------------------------------------------------

def template_headers():
    return [gettext("Date"), gettext("Équipement"), gettext("Point"), gettext("Paramètre"), gettext("Valeur"),
            gettext("Technicien"), gettext("Type"), gettext("Commentaire")]


def build_template():
    """
    Classeur Excel prêt à remplir : feuille « Mesures » (une mesure par ligne, exemples tirés
    des vrais points de l'entreprise), feuille « Référentiel » (tous les points et paramètres
    actifs) et feuille « Lisez-moi ».
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    bold, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E79")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = gettext("Mesures")
    sheet.append(template_headers())
    points = (
        MeasurementPoint.objects.filter(is_active=True, equipment__status__in=["in_service", "stopped", "broken"])
        .select_related("equipment").prefetch_related("parameters").order_by("equipment__code", "code")
    )
    technician = Technician.objects.filter(is_active=True).order_by("employee_number").first()
    now = timezone.localtime().replace(second=0, microsecond=0, tzinfo=None)
    examples = 0
    for point in points:
        for parameter in point.parameters.filter(is_active=True)[:2]:
            if examples >= 3:
                break
            sheet.append([now, point.equipment.code, point.code, parameter.code, None,
                          technician.employee_number if technician else "", str(kind_for([parameter]).label), ""])
            examples += 1
    for row in sheet.iter_rows(min_row=2, max_col=1):
        for cell in row:
            cell.number_format = "DD/MM/YYYY HH:MM"
    for column, width in zip("ABCDEFGH", [18, 16, 12, 14, 12, 14, 20, 40], strict=True):
        sheet.column_dimensions[column].width = width

    reference = workbook.create_sheet(gettext("Référentiel"))
    reference.append([gettext("Équipement"), gettext("Désignation"), gettext("Point"), gettext("Nom du point"), gettext("Paramètre"),
                      gettext("Nom du paramètre"), gettext("Unité"), gettext("Type")])
    for point in points:
        for parameter in point.parameters.filter(is_active=True).order_by("category", "name"):
            reference.append([point.equipment.code, point.equipment.designation, point.code, point.name,
                              parameter.code, parameter.name, parameter.unit, str(kind_for([parameter]).label)])
    for column, width in zip("ABCDEFGH", [16, 36, 12, 34, 14, 34, 10, 20], strict=True):
        reference.column_dimensions[column].width = width
    technicians = workbook.create_sheet(gettext("Techniciens"))
    technicians.append([gettext("Matricule"), gettext("Nom")])
    for tech in Technician.objects.filter(is_active=True).order_by("employee_number"):
        technicians.append([tech.employee_number, str(tech)])
    technicians.column_dimensions["A"].width, technicians.column_dimensions["B"].width = 14, 32

    readme = workbook.create_sheet(gettext("Lisez-moi"))
    for line in [
        gettext("Import de mesures EasyMaint"),
        "",
        gettext("1. Remplissez la feuille « Mesures » : une ligne par mesure."),
        gettext("2. Date : JJ/MM/AAAA HH:MM (cellule date Excel ou texte). Les dates futures sont refusées."),
        gettext("3. Équipement, Point, Paramètre : codes de la feuille « Référentiel ». L'équipement peut être omis si le code du point est unique."),
        gettext("4. Valeur : nombre, virgule ou point décimal."),
        gettext("5. Technicien (facultatif) : matricule de la feuille « Techniciens »."),
        gettext("6. Type (facultatif) : Analyse vibratoire, Analyse d'huile ou Contrôle / relevé ; déduit du paramètre s'il est vide."),
        gettext("7. Une mesure déjà connue (même point, même paramètre, même date) est ignorée."),
        "",
        gettext("Autre disposition acceptée : une colonne par paramètre (titre = code du paramètre, par exemple VIB-V),"),
        gettext("avec les colonnes Date, Équipement et Point. Les fichiers d'appareils en CSV sont aussi acceptés :"),
        gettext("la correspondance des colonnes se règle à l'écran et peut être mémorisée comme « format »."),
    ]:
        readme.append([line])
    readme.column_dimensions["A"].width = 120
    readme["A1"].font = Font(bold=True, size=14)
    for ws in (sheet, reference, technicians):
        for cell in ws[1]:
            cell.font, cell.fill = bold, fill
        ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
