import os
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


def report_upload_to(instance, filename):
    return f"tenant_{instance.tenant_id}/rapports/{instance.year}/{uuid.uuid4().hex}{os.path.splitext(filename)[1]}"


class MonthlyReport(TenantScopedModel):
    """Rapport mensuel de maintenance (PDF), produit chaque mois par le planificateur et conservé dans l'application."""

    year = models.PositiveSmallIntegerField(_("année"), validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    month = models.PositiveSmallIntegerField(_("mois"), validators=[MinValueValidator(1), MaxValueValidator(12)])
    file = models.FileField(_("fichier"), upload_to=report_upload_to)
    generated_at = models.DateTimeField(_("produit le"), auto_now=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name=_("produit par"))

    class Meta:
        verbose_name = _("rapport mensuel")
        verbose_name_plural = _("rapports mensuels")
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["tenant", "year", "month"], name="uniq_monthly_report")]

    def __str__(self):
        return f"{self.month:02d}/{self.year}"
