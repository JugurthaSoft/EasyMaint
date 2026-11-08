import os
import uuid

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


def data_import_upload_to(instance, filename):
    return f"tenant_{instance.tenant_id}/imports-donnees/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}"


class DataImport(TenantScopedModel):
    """Fichier importé (équipements, articles, fournisseurs, historique), conservé avec son bilan."""

    class Kind(models.TextChoices):
        EQUIPMENT = "equipements", _("Équipements")
        SUPPLIERS = "fournisseurs", _("Fournisseurs")
        ITEMS = "articles", _("Articles")
        HISTORY = "historique", _("Historique de maintenance")

    class Status(models.TextChoices):
        DRAFT = "draft", _("À valider")
        DONE = "done", _("Importé")
        CANCELLED = "cancelled", _("Abandonné")

    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    file = models.FileField(_("fichier"), upload_to=data_import_upload_to)
    original_name = models.CharField(_("nom du fichier"), max_length=255)
    update_existing = models.BooleanField(_("mettre à jour les fiches existantes"), default=False)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT)
    total_rows = models.PositiveIntegerField(_("lignes lues"), default=0)
    created_count = models.PositiveIntegerField(_("créées"), default=0)
    updated_count = models.PositiveIntegerField(_("mises à jour"), default=0)
    skipped = models.PositiveIntegerField(_("ignorées"), default=0)
    rejected = models.PositiveIntegerField(_("refusées"), default=0)
    errors = models.JSONField(_("erreurs"), default=list, blank=True)
    imported_at = models.DateTimeField(_("importé le"), null=True, blank=True)

    class Meta:
        verbose_name = _("import de données")
        verbose_name_plural = _("imports de données")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.original_name}"

    def get_absolute_url(self):
        return reverse("imports:detail", args=[self.pk])
