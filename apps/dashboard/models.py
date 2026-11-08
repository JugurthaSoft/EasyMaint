from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class DashboardLayout(TenantScopedModel):
    """Blocs de l'accueil choisis par l'utilisateur, dans son ordre (liste de clés)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard_layout",
                                verbose_name=_("utilisateur"))
    blocks = models.JSONField(_("blocs"), default=list, blank=True)

    class Meta:
        verbose_name = _("présentation de l'accueil")
        verbose_name_plural = _("présentations de l'accueil")

    def __str__(self):
        return str(self.user)
