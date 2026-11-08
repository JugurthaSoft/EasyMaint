"""
Maintenance conditionnelle : paramètres, points de mesure, seuils, tournées, mesures,
alertes et règles de déclenchement.

Le modèle « point × paramètre × seuil » sert pour l'analyse vibratoire, l'analyse
d'huile et tous les contrôles personnalisés : un nouveau type de mesure se crée
comme un paramètre, sans nouvelle table. Aucun seuil n'est fourni par le logiciel :
chaque seuil est saisi par l'utilisateur, avec sa source.
"""
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Equipment
from apps.core.models import TenantScopedModel
from apps.workforce.models import Technician
from apps.workorders.models import Priority, WorkOrder, WorkRequest


class Level(models.TextChoices):
    UNKNOWN = "unknown", _("Sans seuil")
    NORMAL = "normal", _("Normal")
    WARNING = "warning", _("Attention")
    ALARM = "alarm", _("Alarme")
    CRITICAL = "critical", _("Critique")


LEVEL_RANK = {"unknown": 0, "normal": 0, "warning": 1, "alarm": 2, "critical": 3}
LEVEL_BADGES = {"unknown": "b-gray", "normal": "b-green", "warning": "b-orange", "alarm": "b-red", "critical": "b-red"}


class Parameter(TenantScopedModel):
    class Category(models.TextChoices):
        VIBRATION = "vibration", _("Analyse vibratoire")
        OIL = "oil", _("Analyse d'huile")
        TEMPERATURE = "temperature", _("Température")
        PRESSURE = "pressure", _("Pression")
        FLOW = "flow", _("Débit")
        CURRENT = "current", _("Intensité électrique")
        ENERGY = "energy", _("Consommation énergétique")
        THICKNESS = "thickness", _("Épaisseur")
        OTHER = "other", _("Autre")

    class Direction(models.TextChoices):
        RISING = "rising", _("Alerte si la valeur monte")
        FALLING = "falling", _("Alerte si la valeur baisse")
        RANGE = "range", _("Alerte hors d'une plage")

    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("nom"), max_length=120)
    unit = models.CharField(_("unité"), max_length=20, blank=True)
    category = models.CharField(_("catégorie"), max_length=20, choices=Category.choices, default=Category.OTHER)
    direction = models.CharField(_("sens d'alerte"), max_length=10, choices=Direction.choices, default=Direction.RISING)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("paramètre de mesure")
        verbose_name_plural = _("paramètres de mesure")
        ordering = ["category", "name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_parameter_code_per_tenant")]

    def __str__(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name


def point_photo_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"tenant_{instance.tenant_id}/points/{uuid.uuid4().hex}{ext}"


class MeasurementPoint(TenantScopedModel):
    class Direction(models.TextChoices):
        NONE = "", _("—")
        HORIZONTAL = "H", _("Horizontale")
        VERTICAL = "V", _("Verticale")
        AXIAL = "A", _("Axiale")

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="measurement_points", verbose_name=_("équipement"))
    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("nom"), max_length=150)
    position = models.CharField(_("emplacement"), max_length=200, blank=True, help_text=_("Par exemple : palier moteur côté accouplement."))
    direction = models.CharField(_("direction de mesure"), max_length=1, choices=Direction.choices, blank=True, default="")
    parameters = models.ManyToManyField(Parameter, related_name="points", verbose_name=_("paramètres mesurés"))
    photo = models.ImageField(_("photo de l'emplacement"), upload_to=point_photo_upload_to, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("point de mesure")
        verbose_name_plural = _("points de mesure")
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "equipment", "code"], name="uniq_point_code_per_equipment")]

    def __str__(self):
        return f"{self.equipment.code} · {self.name}"

    def get_absolute_url(self):
        return reverse("condition:point_detail", args=[self.pk])

    def clean(self):
        self.check_same_tenant(equipment=self.equipment if self.equipment_id else None)


class Threshold(TenantScopedModel):
    """
    Seuils d'un paramètre sur un point. Chaque modification crée une nouvelle version
    (valable à partir d'une date) : les mesures anciennes restent jugées avec les
    seuils de leur époque.
    """

    class Source(models.TextChoices):
        STANDARD = "standard", _("Norme")
        MANUFACTURER = "manufacturer", _("Constructeur")
        LABORATORY = "laboratory", _("Laboratoire")
        EXPERIENCE = "experience", _("Retour d'expérience")
        OTHER = "other", _("Autre")

    point = models.ForeignKey(MeasurementPoint, on_delete=models.CASCADE, related_name="thresholds", verbose_name=_("point"))
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE, related_name="thresholds", verbose_name=_("paramètre"))
    valid_from = models.DateField(_("applicable à partir du"), default=timezone.localdate)
    warning_high = models.DecimalField(_("attention (haut)"), max_digits=14, decimal_places=4, null=True, blank=True)
    alarm_high = models.DecimalField(_("alarme (haut)"), max_digits=14, decimal_places=4, null=True, blank=True)
    critical_high = models.DecimalField(_("critique (haut)"), max_digits=14, decimal_places=4, null=True, blank=True)
    warning_low = models.DecimalField(_("attention (bas)"), max_digits=14, decimal_places=4, null=True, blank=True)
    alarm_low = models.DecimalField(_("alarme (bas)"), max_digits=14, decimal_places=4, null=True, blank=True)
    critical_low = models.DecimalField(_("critique (bas)"), max_digits=14, decimal_places=4, null=True, blank=True)
    source = models.CharField(_("source"), max_length=20, choices=Source.choices, default=Source.MANUFACTURER)
    reference = models.CharField(_("référence"), max_length=200, blank=True, help_text=_("Norme, document constructeur, rapport…"))

    class Meta:
        verbose_name = _("seuil")
        verbose_name_plural = _("seuils")
        ordering = ["-valid_from", "-pk"]

    def __str__(self):
        return f"{self.point} · {self.parameter.code} ({self.valid_from:%d/%m/%Y})"

    def clean(self):
        self.check_same_tenant(point=self.point if self.point_id else None, parameter=self.parameter if self.parameter_id else None)
        errors = {}
        highs = [(name, getattr(self, name)) for name in ("warning_high", "alarm_high", "critical_high")]
        lows = [(name, getattr(self, name)) for name in ("warning_low", "alarm_low", "critical_low")]
        if all(value is None for _name, value in highs + lows):
            raise ValidationError(_("Renseignez au moins un seuil."))
        defined = [(n, v) for n, v in highs if v is not None]
        for (_n1, v1), (n2, v2) in zip(defined, defined[1:], strict=False):
            if v2 < v1:
                errors[n2] = _("Les seuils hauts doivent croître : attention ≤ alarme ≤ critique.")
        defined = [(n, v) for n, v in lows if v is not None]
        for (_n1, v1), (n2, v2) in zip(defined, defined[1:], strict=False):
            if v2 > v1:
                errors[n2] = _("Les seuils bas doivent décroître : attention ≥ alarme ≥ critique.")
        if errors:
            raise ValidationError(errors)

    def level_for(self, value):
        """Niveau d'une valeur : le plus grave des côtés haut et bas définis."""
        value = Decimal(value)
        level = Level.NORMAL
        for name, candidate in (("critical", Level.CRITICAL), ("alarm", Level.ALARM), ("warning", Level.WARNING)):
            high, low = getattr(self, f"{name}_high"), getattr(self, f"{name}_low")
            if (high is not None and value >= high) or (low is not None and value <= low):
                return candidate
        return level


class MeasurementSession(TenantScopedModel):
    """Tournée de mesures ou prélèvement d'huile sur un équipement."""

    class Kind(models.TextChoices):
        VIBRATION = "vibration", _("Analyse vibratoire")
        OIL = "oil", _("Analyse d'huile")
        INSPECTION = "inspection", _("Contrôle / relevé")

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="measurement_sessions", verbose_name=_("équipement"))
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.INSPECTION)
    measured_at = models.DateTimeField(_("date et heure"), default=timezone.now)
    technician = models.ForeignKey(Technician, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("technicien"))
    rotation_speed = models.DecimalField(_("vitesse de rotation (tr/min)"), max_digits=8, decimal_places=1, null=True, blank=True)
    load_condition = models.CharField(_("régime de fonctionnement"), max_length=150, blank=True)
    observations = models.TextField(_("observations"), blank=True)
    oil_type = models.CharField(_("type d'huile"), max_length=100, blank=True)
    oil_hours = models.DecimalField(_("heures de l'huile"), max_digits=10, decimal_places=1, null=True, blank=True)
    operating_hours = models.DecimalField(_("heures de fonctionnement"), max_digits=12, decimal_places=1, null=True, blank=True)
    laboratory = models.CharField(_("laboratoire"), max_length=150, blank=True)
    lab_report_number = models.CharField(_("n° de rapport"), max_length=60, blank=True)
    lab_conclusion = models.TextField(_("conclusion du laboratoire"), blank=True)
    source_import = models.ForeignKey(
        "MeasurementImport", on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions",
        verbose_name=_("import d'origine"),
    )
    source_api = models.BooleanField(_("reçue par l'API"), default=False)

    class Meta:
        verbose_name = _("tournée de mesures")
        verbose_name_plural = _("tournées de mesures")
        ordering = ["-measured_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.equipment.code} · {timezone.localtime(self.measured_at):%d/%m/%Y}"

    def get_absolute_url(self):
        return reverse("condition:session_detail", args=[self.pk])


class Measurement(TenantScopedModel):
    session = models.ForeignKey(MeasurementSession, on_delete=models.CASCADE, related_name="measurements")
    point = models.ForeignKey(MeasurementPoint, on_delete=models.CASCADE, related_name="measurements", verbose_name=_("point"))
    parameter = models.ForeignKey(Parameter, on_delete=models.PROTECT, related_name="measurements", verbose_name=_("paramètre"))
    value = models.DecimalField(_("valeur"), max_digits=14, decimal_places=4)
    level = models.CharField(_("niveau"), max_length=10, choices=Level.choices, default=Level.UNKNOWN)
    threshold = models.ForeignKey(Threshold, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    measured_at = models.DateTimeField(_("date"))

    class Meta:
        verbose_name = _("mesure")
        verbose_name_plural = _("mesures")
        ordering = ["-measured_at", "-pk"]
        indexes = [models.Index(fields=["point", "parameter", "measured_at"], name="measure_series_idx")]

    def __str__(self):
        return f"{self.point} · {self.parameter.code} = {self.value}"

    @property
    def level_badge(self):
        return LEVEL_BADGES.get(self.level, "b-gray")


class TriggerRule(TenantScopedModel):
    """Au-delà d'un niveau (et après N mesures consécutives), crée une demande ou un OT conditionnel."""

    class Action(models.TextChoices):
        REQUEST = "request", _("Créer une demande d'intervention")
        WORK_ORDER = "work_order", _("Créer un OT conditionnel")

    LEVEL_CHOICES = [(Level.WARNING, _("Attention")), (Level.ALARM, _("Alarme")), (Level.CRITICAL, _("Critique"))]

    name = models.CharField(_("nom"), max_length=150)
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE, related_name="rules", verbose_name=_("paramètre"))
    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name=_("équipement"),
        help_text=_("Laisser vide pour appliquer la règle à tous les équipements."),
    )
    min_level = models.CharField(_("à partir du niveau"), max_length=10, choices=LEVEL_CHOICES, default=Level.ALARM)
    consecutive = models.PositiveSmallIntegerField(
        _("mesures consécutives"), default=1, validators=[MinValueValidator(1)],
        help_text=_("Nombre de mesures successives au moins à ce niveau avant d'agir."),
    )
    action = models.CharField(_("action"), max_length=20, choices=Action.choices, default=Action.REQUEST)
    priority = models.PositiveSmallIntegerField(_("priorité"), choices=Priority.choices, default=Priority.HIGH)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("règle de déclenchement")
        verbose_name_plural = _("règles de déclenchement")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        self.check_same_tenant(parameter=self.parameter if self.parameter_id else None, equipment=self.equipment)


class Alert(TenantScopedModel):
    """Une alerte par point et paramètre tant qu'elle n'est pas close : les mesures suivantes la mettent à jour."""

    class Status(models.TextChoices):
        OPEN = "open", _("Ouverte")
        ACKNOWLEDGED = "acknowledged", _("Acquittée")
        CLOSED = "closed", _("Close")

    point = models.ForeignKey(MeasurementPoint, on_delete=models.CASCADE, related_name="alerts", verbose_name=_("point"))
    parameter = models.ForeignKey(Parameter, on_delete=models.CASCADE, related_name="alerts", verbose_name=_("paramètre"))
    level = models.CharField(_("niveau"), max_length=10, choices=Level.choices)
    max_level = models.CharField(_("niveau le plus grave"), max_length=10, choices=Level.choices)
    status = models.CharField(_("statut"), max_length=15, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(_("ouverte le"), default=timezone.now)
    first_measurement = models.ForeignKey(Measurement, on_delete=models.SET_NULL, null=True, related_name="+")
    last_measurement = models.ForeignKey(Measurement, on_delete=models.SET_NULL, null=True, related_name="+")
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(_("commentaire"), max_length=255, blank=True)
    rule = models.ForeignKey(TriggerRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts")
    work_request = models.ForeignKey(WorkRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = _("alerte")
        verbose_name_plural = _("alertes")
        ordering = ["-opened_at"]
        indexes = [models.Index(fields=["tenant", "status"], name="alert_status_idx")]

    def __str__(self):
        return f"{self.point} · {self.parameter.name} · {self.get_level_display()}"

    def get_absolute_url(self):
        return reverse("condition:alert_detail", args=[self.pk])

    @property
    def is_active(self):
        return self.status != self.Status.CLOSED

    @property
    def level_badge(self):
        return LEVEL_BADGES.get(self.level, "b-gray")

    @property
    def back_to_normal(self):
        return self.level == Level.NORMAL


class ImportProfile(TenantScopedModel):
    """Correspondance mémorisée entre les colonnes d'un fichier d'appareil et les champs d'EasyMaint."""

    name = models.CharField(_("nom"), max_length=150)
    mapping = models.JSONField(_("correspondance des colonnes"), default=dict, blank=True)

    class Meta:
        verbose_name = _("format d'import")
        verbose_name_plural = _("formats d'import")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_import_profile_name_per_tenant")]

    def __str__(self):
        return self.name


def import_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"tenant_{instance.tenant_id}/imports/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class MeasurementImport(TenantScopedModel):
    """Un fichier importé : conservé, avec la correspondance utilisée et le bilan ligne à ligne."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("À valider")
        DONE = "done", _("Importé")
        CANCELLED = "cancelled", _("Abandonné")

    file = models.FileField(_("fichier"), upload_to=import_upload_to)
    original_name = models.CharField(_("nom du fichier"), max_length=255)
    profile = models.ForeignKey(ImportProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="imports",
                                verbose_name=_("format"))
    mapping = models.JSONField(_("correspondance des colonnes"), default=dict, blank=True)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    total_rows = models.PositiveIntegerField(_("lignes lues"), default=0)
    imported = models.PositiveIntegerField(_("mesures importées"), default=0)
    skipped = models.PositiveIntegerField(_("doublons ignorés"), default=0)
    rejected = models.PositiveIntegerField(_("lignes refusées"), default=0)
    sessions_created = models.PositiveIntegerField(_("tournées créées"), default=0)
    errors = models.JSONField(_("erreurs"), default=list, blank=True)
    imported_at = models.DateTimeField(_("importé le"), null=True, blank=True)

    class Meta:
        verbose_name = _("import de mesures")
        verbose_name_plural = _("imports de mesures")
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name

    def get_absolute_url(self):
        return reverse("condition:import_detail", args=[self.pk])
