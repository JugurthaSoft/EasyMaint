"""Budget annuel de maintenance par unité, réparti par mois (les dépenses réelles viennent des OT et du magasin)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Location
from apps.core.models import TenantScopedModel

MONTH_FIELDS = [f"month_{index:02d}" for index in range(1, 13)]


class Budget(TenantScopedModel):
    year = models.PositiveSmallIntegerField(_("année"), validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    unit = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+", verbose_name=_("unité"))
    month_01 = models.DecimalField(_("janvier"), max_digits=14, decimal_places=3, default=0)
    month_02 = models.DecimalField(_("février"), max_digits=14, decimal_places=3, default=0)
    month_03 = models.DecimalField(_("mars"), max_digits=14, decimal_places=3, default=0)
    month_04 = models.DecimalField(_("avril"), max_digits=14, decimal_places=3, default=0)
    month_05 = models.DecimalField(_("mai"), max_digits=14, decimal_places=3, default=0)
    month_06 = models.DecimalField(_("juin"), max_digits=14, decimal_places=3, default=0)
    month_07 = models.DecimalField(_("juillet"), max_digits=14, decimal_places=3, default=0)
    month_08 = models.DecimalField(_("août"), max_digits=14, decimal_places=3, default=0)
    month_09 = models.DecimalField(_("septembre"), max_digits=14, decimal_places=3, default=0)
    month_10 = models.DecimalField(_("octobre"), max_digits=14, decimal_places=3, default=0)
    month_11 = models.DecimalField(_("novembre"), max_digits=14, decimal_places=3, default=0)
    month_12 = models.DecimalField(_("décembre"), max_digits=14, decimal_places=3, default=0)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("budget de maintenance")
        verbose_name_plural = _("budgets de maintenance")
        ordering = ["year", "unit__name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "year", "unit"], name="uniq_budget_year_unit")]

    def __str__(self):
        return f"{self.year} · {self.unit}"

    def clean(self):
        self.check_same_tenant(unit=self.unit if self.unit_id else None)
        if self.unit_id and self.unit.kind != Location.Kind.WORKSHOP:
            raise ValidationError({"unit": _("Le budget se définit par unité.")})
        for name in MONTH_FIELDS:
            if getattr(self, name) is not None and getattr(self, name) < 0:
                raise ValidationError({name: _("Montant négatif.")})

    @property
    def months(self):
        return [getattr(self, name) or Decimal("0") for name in MONTH_FIELDS]

    @property
    def annual(self):
        return sum(self.months, Decimal("0"))
