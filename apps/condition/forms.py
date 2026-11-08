from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.forms import DateInput, DateTimeInput
from apps.assets.models import Equipment
from apps.workforce.models import Technician
from apps.workorders.forms import EquipmentChoiceField

from .models import (
    MeasurementPoint,
    MeasurementSession,
    Parameter,
    Threshold,
    TriggerRule,
)


class ParameterForm(forms.ModelForm):
    class Meta:
        model = Parameter
        fields = ["code", "name", "unit", "category", "direction", "is_active"]

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        duplicates = Parameter.objects.filter(code__iexact=code)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("Ce code est déjà utilisé dans votre entreprise."))
        return code


class PointForm(forms.ModelForm):
    class Meta:
        model = MeasurementPoint
        fields = ["code", "name", "position", "direction", "parameters", "photo", "notes", "is_active"]
        widgets = {
            "parameters": forms.CheckboxSelectMultiple,
            "notes": forms.Textarea(attrs={"rows": 2}),
            "photo": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, equipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.equipment = equipment or getattr(self.instance, "equipment", None)
        active = Parameter.objects.filter(is_active=True)
        if self.instance.pk:
            active = active | Parameter.objects.filter(pk__in=self.instance.parameters.values("pk"))
        self.fields["parameters"].queryset = active.distinct().order_by("category", "name")

    def parameter_groups(self):
        """
        Paramètres regroupés par catégorie, dans l'ordre métier (vibratoire, huile, température…),
        avec leur état coché, pour un affichage en sections titrées.
        """
        selected = {str(getattr(value, "pk", value)) for value in (self["parameters"].value() or [])}
        by_category = {}
        for parameter in self.fields["parameters"].queryset:
            by_category.setdefault(parameter.category, []).append(parameter)
        groups = []
        for value, label in Parameter.Category.choices:
            items = sorted(by_category.get(value, []), key=lambda p: p.name.lower())
            if items:
                groups.append((label, [(p.pk, str(p), str(p.pk) in selected) for p in items]))
        return groups

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        duplicates = MeasurementPoint.objects.filter(equipment=self.equipment, code__iexact=code)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("Ce code existe déjà sur cet équipement."))
        return code


class ThresholdForm(forms.ModelForm):
    """Nouvelle version des seuils d'un paramètre sur un point."""

    class Meta:
        model = Threshold
        fields = ["warning_high", "alarm_high", "critical_high", "warning_low", "alarm_low", "critical_low",
                  "source", "reference", "valid_from"]
        widgets = {"valid_from": DateInput()}


class RuleForm(forms.ModelForm):
    equipment = EquipmentChoiceField(queryset=Equipment.objects.none(), required=False, label=_("Équipement"),
                                     help_text=_("Laisser vide pour appliquer la règle à tous les équipements."))

    class Meta:
        model = TriggerRule
        fields = ["name", "parameter", "equipment", "min_level", "consecutive", "action", "priority", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parameter"].queryset = Parameter.objects.filter(is_active=True)
        self.fields["equipment"].queryset = Equipment.objects.exclude(status=Equipment.Status.RETIRED).order_by("code")
        self.fields["equipment"].empty_label = _("— Tous les équipements —")


class SessionHeaderForm(forms.ModelForm):
    """En-tête d'une tournée ; les valeurs sont lues dans la grille (champs v-<point>-<paramètre>)."""

    report = forms.FileField(label=_("Rapport ou fichier de mesure (facultatif)"), required=False)

    class Meta:
        model = MeasurementSession
        fields = [
            "kind", "measured_at", "technician", "rotation_speed", "load_condition", "observations",
            "oil_type", "oil_hours", "operating_hours", "laboratory", "lab_report_number", "lab_conclusion",
        ]
        widgets = {
            "measured_at": DateTimeInput(),
            "observations": forms.Textarea(attrs={"rows": 2}),
            "lab_conclusion": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, technician=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["technician"].queryset = Technician.objects.filter(is_active=True)
        if not self.is_bound:
            self.initial.setdefault("measured_at", timezone.localtime().replace(second=0, microsecond=0))
            if technician is not None:
                self.initial.setdefault("technician", technician.pk)


class CommentForm(forms.Form):
    comment = forms.CharField(label=_("Commentaire"), max_length=255, required=False)
