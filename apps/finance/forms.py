from decimal import ROUND_DOWN, Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import MONTH_FIELDS, Budget


class BudgetForm(forms.ModelForm):
    """Budget d'une unité pour une année : montant annuel réparti à parts égales, ou mois par mois."""

    annual = forms.DecimalField(label=_("Budget annuel"), max_digits=14, decimal_places=3, min_value=Decimal("0"), required=False,
                                help_text=_("Renseigné et « Répartir à parts égales » coché : les 12 mois sont recalculés."))
    split = forms.BooleanField(label=_("Répartir à parts égales sur les 12 mois"), required=False)

    class Meta:
        model = Budget
        fields = [*MONTH_FIELDS, "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in MONTH_FIELDS:
            self.fields[name].min_value = Decimal("0")
            self.fields[name].required = False
        if self.instance.pk:
            self.initial.setdefault("annual", self.instance.annual)

    def clean(self):
        cleaned = super().clean()
        for name in MONTH_FIELDS:
            if name in self.errors:
                continue  # déjà refusé par le champ (texte non numérique…)
            value = cleaned.get(name)
            if value is None:
                cleaned[name] = Decimal("0")
            elif value < 0:
                self.add_error(name, _("Montant négatif."))
        if cleaned.get("split") and not self.errors:
            annual = cleaned.get("annual")
            if annual is None:
                self.add_error("annual", _("Indiquez le budget annuel à répartir."))
            else:
                share = (annual / 12).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
                for name in MONTH_FIELDS:
                    cleaned[name] = share
                cleaned[MONTH_FIELDS[-1]] = annual - share * 11  # le reste d'arrondi sur décembre
        for name in MONTH_FIELDS:
            if name in cleaned:
                setattr(self.instance, name, cleaned[name])
        return cleaned
