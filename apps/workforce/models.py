"""Ressources de maintenance : compétences, équipes, techniciens, sous-traitants."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Skill(TenantScopedModel):
    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("nom"), max_length=100)

    class Meta:
        verbose_name = _("compétence")
        verbose_name_plural = _("compétences")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_skill_code_per_tenant")]

    def __str__(self):
        return self.name


class Team(TenantScopedModel):
    name = models.CharField(_("nom"), max_length=100)
    leader = models.ForeignKey(
        "Technician", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("chef d'équipe"),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("équipe")
        verbose_name_plural = _("équipes")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_team_name_per_tenant")]

    def __str__(self):
        return self.name

    def clean(self):
        self.check_same_tenant(leader=self.leader)


class Technician(TenantScopedModel):
    """Intervenant interne. Peut être relié à un compte utilisateur pour exécuter ses OT dans l'application."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="technician",
        verbose_name=_("compte utilisateur"),
    )
    employee_number = models.CharField(_("matricule"), max_length=30)
    first_name = models.CharField(_("prénom"), max_length=100)
    last_name = models.CharField(_("nom"), max_length=100)
    function = models.CharField(_("fonction"), max_length=100, blank=True)
    specialty = models.CharField(_("spécialité"), max_length=100, blank=True)
    skills = models.ManyToManyField(Skill, blank=True, related_name="technicians", verbose_name=_("compétences"))
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="members", verbose_name=_("équipe"),
    )
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    hourly_rate = models.DecimalField(
        _("coût horaire"), max_digits=10, decimal_places=3, default=0, validators=[MinValueValidator(0)],
    )
    overtime_rate = models.DecimalField(
        _("coût horaire heures supplémentaires"), max_digits=10, decimal_places=3, default=0,
        validators=[MinValueValidator(0)], help_text=_("Laisser à 0 pour appliquer le coût horaire normal."),
    )
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("technicien")
        verbose_name_plural = _("techniciens")
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "employee_number"], name="uniq_technician_number_per_tenant"),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def short_name(self):
        return f"{self.first_name[:1]}. {self.last_name}".strip()

    def rate_for(self, overtime=False):
        """Taux appliqué à une heure de travail, figé au moment de la saisie du temps."""
        if overtime and self.overtime_rate and self.overtime_rate > 0:
            return self.overtime_rate
        return self.hourly_rate or Decimal("0")

    def clean(self):
        self.check_same_tenant(team=self.team, user=self.user)


class Contractor(TenantScopedModel):
    """Entreprise sous-traitante (électricité, levage, usinage...)."""

    name = models.CharField(_("raison sociale"), max_length=150)
    contact_name = models.CharField(_("contact"), max_length=150, blank=True)
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    specialties = models.CharField(_("spécialités"), max_length=200, blank=True)
    hourly_rate = models.DecimalField(_("taux horaire indicatif"), max_digits=10, decimal_places=3, default=0)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("sous-traitant")
        verbose_name_plural = _("sous-traitants")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="uniq_contractor_name_per_tenant")]

    def __str__(self):
        return self.name


def technician_for(user):
    """Fiche technicien liée à un compte, ou None (sans exception)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        technician = user.technician
    except Technician.DoesNotExist:
        return None
    if technician is None or technician.tenant_id != user.tenant_id or not technician.is_active:
        return None
    return technician

