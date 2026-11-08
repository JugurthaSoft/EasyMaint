from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from apps.core.models import Tenant, TenantScopedModel

from .capabilities import ALL_CAPABILITIES


class Role(TenantScopedModel):
    """Profil d'utilisateur propre à une entreprise : un nom et une liste de capacités."""

    code = models.SlugField(_("code"), max_length=50)
    name = models.CharField(_("nom"), max_length=100)
    capabilities = models.JSONField(_("capacités"), default=list, blank=True)
    is_system = models.BooleanField(
        _("rôle prédéfini"), default=False,
        help_text=_("Les rôles prédéfinis peuvent être ajustés mais pas supprimés."),
    )

    class Meta:
        verbose_name = _("rôle")
        verbose_name_plural = _("rôles")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_role_code_per_tenant")]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        """Nom affiché : un rôle prédéfini dont le nom n'a pas été changé suit la langue de l'utilisateur."""
        from django.utils import translation

        from .capabilities import DEFAULT_ROLES

        if self.is_system and self.code in DEFAULT_ROLES:
            label = DEFAULT_ROLES[self.code][0]
            with translation.override("fr"):
                original = str(label)
            if self.name == original:
                return str(label)
        return self.name

    def save(self, *args, **kwargs):
        # On ne garde que des capacités connues, triées, sans doublon.
        self.capabilities = sorted(set(self.capabilities or []) & set(ALL_CAPABILITIES))
        super().save(*args, **kwargs)


class User(AbstractUser):
    """
    Utilisateur. Rattaché à une seule entreprise ; seul le super-administrateur
    de la plateforme n'en a pas (il n'accède qu'à l'administration technique).
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, null=True, blank=True, related_name="users", verbose_name=_("entreprise"),
    )
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, null=True, blank=True, related_name="users", verbose_name=_("rôle"),
    )
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    job_title = models.CharField(_("fonction"), max_length=100, blank=True)

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.get_full_name() or self.username

    @cached_property
    def capability_set(self):
        if not self.is_active:
            return frozenset()
        if self.role_id is None:
            return frozenset()
        return frozenset(self.role.capabilities)

    def has_capability(self, code):
        """Vrai si l'utilisateur dispose de la capacité dans son entreprise."""
        if not self.is_active or self.tenant_id is None:
            return False
        return code in self.capability_set

    @property
    def initials(self):
        parts = [self.first_name[:1], self.last_name[:1]]
        return ("".join(parts) or self.username[:2]).upper()
