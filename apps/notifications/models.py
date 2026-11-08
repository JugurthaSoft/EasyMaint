"""Notifications affichées dans l'application (cloche de la barre supérieure). Aucun envoi externe."""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Notification(TenantScopedModel):
    class Kind(models.TextChoices):
        ASSIGNED = "assigned", _("OT affecté")
        REQUEST = "request", _("Nouvelle demande")
        ALERT = "alert", _("Alerte conditionnelle")
        PART = "part", _("Demande de pièce")
        TO_VALIDATE = "to_validate", _("OT à valider")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications",
                             verbose_name=_("destinataire"))
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    title = models.CharField(_("titre"), max_length=200)
    body = models.CharField(_("détail"), max_length=255, blank=True)
    url = models.CharField(_("lien"), max_length=300, blank=True)
    read_at = models.DateTimeField(_("lue le"), null=True, blank=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["user", "read_at"], name="notif_user_read_idx")]

    def __str__(self):
        return self.title

    @property
    def is_read(self):
        return self.read_at is not None
