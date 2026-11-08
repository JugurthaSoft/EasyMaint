"""Patrimoine : localisations, familles, fabricants, équipements, compteurs."""
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Location(TenantScopedModel):
    """Arborescence libre : usine › unité › ligne › zone. Les niveaux ligne et zone sont facultatifs."""

    class Kind(models.TextChoices):
        SITE = "site", _("Usine")
        WORKSHOP = "workshop", _("Unité")
        LINE = "line", _("Ligne de production")
        ZONE = "zone", _("Zone")

    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("nom"), max_length=150)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.WORKSHOP)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children", verbose_name=_("parent"),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("localisation")
        verbose_name_plural = _("localisations")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_location_code_per_tenant")]

    def __str__(self):
        return self.name

    def ancestors(self):
        """Liste des parents, du plus haut au plus proche."""
        chain, node, seen = [], self.parent, set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.insert(0, node)
            node = node.parent
        return chain

    @property
    def full_path(self):
        return " › ".join([a.name for a in self.ancestors()] + [self.name])

    def clean(self):
        self.check_same_tenant(parent=self.parent)
        if self.parent_id and self.pk:
            node = self.parent
            while node is not None:
                if node.pk == self.pk:
                    raise ValidationError({"parent": _("Une localisation ne peut pas être placée sous elle-même.")})
                node = node.parent


class EquipmentFamily(TenantScopedModel):
    """Famille d'équipements, avec un niveau de catégorie optionnel (Presses › Injection)."""

    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("nom"), max_length=150)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children",
        verbose_name=_("famille parente"),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("famille d'équipements")
        verbose_name_plural = _("familles d'équipements")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_family_code_per_tenant")]

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    def clean(self):
        self.check_same_tenant(parent=self.parent)
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": _("Une famille ne peut pas être sa propre parente.")})
        if self.parent_id and self.parent.parent_id:
            raise ValidationError({"parent": _("Deux niveaux maximum : famille › catégorie.")})


class Manufacturer(TenantScopedModel):
    name = models.CharField(_("nom"), max_length=150)
    website = models.URLField(_("site web"), blank=True)
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("fabricant")
        verbose_name_plural = _("fabricants")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_manufacturer_name_per_tenant")]

    def __str__(self):
        return self.name


def equipment_photo_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"tenant_{instance.tenant_id}/equipements/{uuid.uuid4().hex}{ext}"


class Equipment(TenantScopedModel):
    class Status(models.TextChoices):
        IN_SERVICE = "in_service", _("En service")
        STOPPED = "stopped", _("Arrêté")
        BROKEN = "broken", _("En panne")
        RETIRED = "retired", _("Réformé")

    class Criticality(models.TextChoices):
        A = "A", _("A — critique")
        B = "B", _("B — importante")
        C = "C", _("C — secondaire")

    STATUS_BADGES = {
        "in_service": "b-green", "stopped": "b-gray", "broken": "b-red", "retired": "b-muted",
    }

    code = models.CharField(_("code"), max_length=40)
    designation = models.CharField(_("désignation"), max_length=200)
    family = models.ForeignKey(EquipmentFamily, on_delete=models.PROTECT, related_name="equipment", verbose_name=_("famille"))
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment", verbose_name=_("fabricant"),
    )
    brand = models.CharField(_("marque"), max_length=100, blank=True)
    model = models.CharField(_("modèle"), max_length=100, blank=True)
    serial_number = models.CharField(_("n° de série"), max_length=100, blank=True)
    commissioning_date = models.DateField(_("date de mise en service"), null=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="equipment", verbose_name=_("localisation"))
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children",
        verbose_name=_("équipement parent"), help_text=_("Renseigner pour un sous-équipement."),
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("responsable"),
    )
    status = models.CharField(_("état"), max_length=20, choices=Status.choices, default=Status.IN_SERVICE)
    criticality = models.CharField(_("criticité"), max_length=1, choices=Criticality.choices, default=Criticality.B)
    photo = models.ImageField(_("photo"), upload_to=equipment_photo_upload_to, blank=True)
    required_hours_per_day = models.DecimalField(
        _("heures requises par jour"), max_digits=4, decimal_places=1, default=16,
        validators=[MinValueValidator(0), MaxValueValidator(24)],
        help_text=_("Temps d'ouverture prévu, utilisé pour la disponibilité."),
    )
    operating_days_per_week = models.PositiveSmallIntegerField(
        _("jours de fonctionnement par semaine"), default=6, validators=[MinValueValidator(1), MaxValueValidator(7)],
        help_text=_("Du lundi au samedi pour 6 ; utilisé avec les heures requises pour le temps requis (MTBF, disponibilité)."),
    )
    notes = models.TextField(_("notes"), blank=True)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        verbose_name = _("équipement")
        verbose_name_plural = _("équipements")
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_equipment_code_per_tenant")]
        indexes = [models.Index(fields=["tenant", "status"], name="equipment_status_idx")]

    def __str__(self):
        return f"{self.code} · {self.designation}"

    def get_absolute_url(self):
        return reverse("assets:equipment_detail", args=[self.pk])

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, "b-gray")

    def clean(self):
        self.check_same_tenant(
            location=getattr(self, "location", None) if self.location_id else None,
            family=getattr(self, "family", None) if self.family_id else None,
            manufacturer=self.manufacturer, parent=self.parent, responsible=self.responsible,
        )
        if self.parent_id:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError({"parent": _("Un équipement ne peut pas être son propre parent.")})
            node, seen = self.parent, set()
            while node is not None and node.pk not in seen:
                if self.pk and node.pk == self.pk:
                    raise ValidationError({"parent": _("Ce choix créerait une boucle entre équipements.")})
                seen.add(node.pk)
                node = node.parent


class Meter(TenantScopedModel):
    class Kind(models.TextChoices):
        HOURS = "hours", _("Heures de fonctionnement")
        CYCLES = "cycles", _("Nombre de cycles")
        DISTANCE = "distance", _("Kilométrage")
        CUSTOM = "custom", _("Personnalisé")

    DEFAULT_UNITS = {"hours": "h", "cycles": "cycles", "distance": "km", "custom": ""}

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="meters", verbose_name=_("équipement"))
    name = models.CharField(_("nom"), max_length=100)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, default=Kind.HOURS)
    unit = models.CharField(_("unité"), max_length=20, blank=True)
    is_cumulative = models.BooleanField(
        _("cumulatif"), default=True, help_text=_("Un compteur cumulatif ne peut jamais diminuer."),
    )
    current_value = models.DecimalField(_("valeur actuelle"), max_digits=14, decimal_places=2, default=0)
    last_reading_at = models.DateTimeField(_("dernier relevé"), null=True, blank=True)

    class Meta:
        verbose_name = _("compteur")
        verbose_name_plural = _("compteurs")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["equipment", "name"], name="uniq_meter_name_per_equipment")]

    def __str__(self):
        return f"{self.equipment.code} · {self.name}"

    def save(self, *args, **kwargs):
        if not self.unit:
            self.unit = self.DEFAULT_UNITS.get(self.kind, "")
        super().save(*args, **kwargs)


class MeterReading(TenantScopedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", _("Saisie")
        WORKORDER = "workorder", _("Ordre de travail")
        IMPORT = "import", _("Import")
        SENSOR = "sensor", _("Capteur")

    meter = models.ForeignKey(Meter, on_delete=models.CASCADE, related_name="readings", verbose_name=_("compteur"))
    reading_at = models.DateTimeField(_("date du relevé"))
    value = models.DecimalField(_("valeur"), max_digits=14, decimal_places=2)
    source = models.CharField(_("origine"), max_length=20, choices=Source.choices, default=Source.MANUAL)
    note = models.CharField(_("commentaire"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("relevé de compteur")
        verbose_name_plural = _("relevés de compteurs")
        ordering = ["-reading_at"]
        indexes = [models.Index(fields=["meter", "reading_at"], name="reading_meter_date_idx")]

    def __str__(self):
        return f"{self.meter} : {self.value} ({self.reading_at:%d/%m/%Y})"
