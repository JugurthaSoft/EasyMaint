"""
Plans de maintenance préventive.

Un plan porte son déclencheur : calendrier (tous les N jours, semaines, mois, ans),
compteur (toutes les N heures, cycles, km) ou les deux (« le premier atteint »).
Les OT préventifs sont générés par apps.preventive.services.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Equipment, Meter
from apps.core.formatting import smart_number
from apps.core.models import TenantScopedModel
from apps.workforce.models import Skill, Team, Technician
from apps.workorders.models import Priority


class PreventivePlan(TenantScopedModel):
    class TriggerMode(models.TextChoices):
        CALENDAR = "calendar", _("Calendrier")
        METER = "meter", _("Compteur")
        BOTH = "both", _("Calendrier et compteur (le premier atteint)")

    class PeriodUnit(models.TextChoices):
        DAY = "day", _("jour(s)")
        WEEK = "week", _("semaine(s)")
        MONTH = "month", _("mois")
        YEAR = "year", _("an(s)")

    class Basis(models.TextChoices):
        FIXED = "fixed", _("Fixe : à partir de l'échéance prévue")
        FLOATING = "floating", _("Glissante : à partir de la date de réalisation")

    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("intitulé"), max_length=200)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="preventive_plans", verbose_name=_("équipement"))
    operations = models.TextField(_("opération à effectuer"))
    instructions = models.TextField(_("instructions techniques"), blank=True)
    estimated_hours = models.DecimalField(
        _("temps estimé (h)"), max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
    )
    priority = models.PositiveSmallIntegerField(_("priorité des OT"), choices=Priority.choices, default=Priority.NORMAL)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("équipe"))
    technicians = models.ManyToManyField(Technician, blank=True, related_name="preventive_plans", verbose_name=_("techniciens"))
    skills = models.ManyToManyField(Skill, blank=True, related_name="+", verbose_name=_("compétences nécessaires"))

    trigger_mode = models.CharField(_("déclenchement"), max_length=10, choices=TriggerMode.choices, default=TriggerMode.CALENDAR)
    period_value = models.PositiveSmallIntegerField(_("tous les"), null=True, blank=True, validators=[MinValueValidator(1)])
    period_unit = models.CharField(_("unité"), max_length=10, choices=PeriodUnit.choices, default=PeriodUnit.MONTH)
    next_due_date = models.DateField(_("prochaine échéance"), null=True, blank=True)
    schedule_basis = models.CharField(_("périodicité"), max_length=10, choices=Basis.choices, default=Basis.FIXED)
    lead_days = models.PositiveSmallIntegerField(
        _("anticipation (jours)"), default=7, help_text=_("L'OT est créé ce nombre de jours avant l'échéance."),
    )
    meter = models.ForeignKey(Meter, on_delete=models.PROTECT, null=True, blank=True, related_name="preventive_plans", verbose_name=_("compteur"))
    meter_interval = models.DecimalField(
        _("toutes les (unités du compteur)"), max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    meter_lead = models.DecimalField(
        _("anticipation (unités du compteur)"), max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text=_("Par exemple 100 h : l'OT est créé 100 h avant le seuil."),
    )
    last_done_meter = models.DecimalField(
        _("compteur au dernier entretien"), max_digits=14, decimal_places=2, null=True, blank=True,
        help_text=_("Laisser vide pour partir de la valeur actuelle du compteur."),
    )
    last_done_date = models.DateField(_("dernière réalisation"), null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("plan préventif")
        verbose_name_plural = _("plans préventifs")
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_plan_code_per_tenant")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def get_absolute_url(self):
        return reverse("preventive:plan_detail", args=[self.pk])

    @property
    def uses_calendar(self):
        return self.trigger_mode in (self.TriggerMode.CALENDAR, self.TriggerMode.BOTH)

    @property
    def uses_meter(self):
        return self.trigger_mode in (self.TriggerMode.METER, self.TriggerMode.BOTH)

    @property
    def next_meter_threshold(self):
        if not self.uses_meter or self.meter_interval is None or self.last_done_meter is None:
            return None
        return self.last_done_meter + self.meter_interval

    @property
    def period_label(self):
        if not self.period_value:
            return ""
        unit = self.PeriodUnit(self.period_unit).label
        if self.period_value == 1:
            return str(_("chaque %(unit)s") % {"unit": {"day": _("jour"), "week": _("semaine"), "month": _("mois"), "year": _("année")}[self.period_unit]})
        return str(_("tous les %(n)s %(unit)s") % {"n": self.period_value, "unit": unit})

    @property
    def meter_label(self):
        if self.meter_interval is None or self.meter_id is None:
            return ""
        return str(_("toutes les %(n)s %(unit)s") % {"n": smart_number(self.meter_interval), "unit": self.meter.unit})

    @property
    def trigger_summary(self):
        parts = []
        if self.uses_calendar:
            parts.append(self.period_label)
        if self.uses_meter:
            parts.append(self.meter_label)
        text = str(_(" ou ")).join(p for p in parts if p)
        return text[:1].upper() + text[1:]

    def clean(self):
        self.check_same_tenant(
            equipment=self.equipment if self.equipment_id else None, team=self.team, meter=self.meter,
        )
        errors = {}
        if self.uses_calendar:
            if not self.period_value:
                errors["period_value"] = _("Indiquez la périodicité.")
            if not self.next_due_date:
                errors["next_due_date"] = _("Indiquez la première échéance.")
        if self.uses_meter:
            if self.meter_id is None:
                errors["meter"] = _("Choisissez le compteur.")
            elif self.equipment_id and self.meter.equipment_id != self.equipment_id:
                errors["meter"] = _("Ce compteur appartient à un autre équipement.")
            if not self.meter_interval or self.meter_interval <= 0:
                errors["meter_interval"] = _("Indiquez l'intervalle du compteur.")
            elif self.meter_lead is not None and self.meter_lead >= self.meter_interval:
                errors["meter_lead"] = _("L'anticipation doit être inférieure à l'intervalle.")
        if errors:
            raise ValidationError(errors)


class PlanChecklistItem(TenantScopedModel):
    plan = models.ForeignKey(PreventivePlan, on_delete=models.CASCADE, related_name="checklist")
    position = models.PositiveSmallIntegerField(default=0)
    label = models.CharField(_("point de contrôle"), max_length=255)

    class Meta:
        verbose_name = _("point de contrôle du plan")
        verbose_name_plural = _("check-list du plan")
        ordering = ["position", "pk"]

    def __str__(self):
        return self.label


class PlanPart(TenantScopedModel):
    """
    Pièce prévue par le plan : article du magasin (réservé automatiquement à la création de l'OT)
    ou saisie libre (pièce non stockée).
    """

    plan = models.ForeignKey(PreventivePlan, on_delete=models.CASCADE, related_name="parts")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                             verbose_name=_("article du magasin"))
    reference = models.CharField(_("référence"), max_length=60, blank=True)
    designation = models.CharField(_("désignation"), max_length=200)
    quantity = models.DecimalField(_("quantité"), max_digits=12, decimal_places=3, default=1, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = _("pièce prévue")
        verbose_name_plural = _("pièces prévues")
        ordering = ["pk"]

    def __str__(self):
        return self.designation
