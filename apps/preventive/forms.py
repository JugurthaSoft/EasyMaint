from django import forms
from django.utils.translation import gettext_lazy as _

from apps.assets.forms import DateInput
from apps.assets.models import Equipment, Meter
from apps.inventory.forms import ItemReferenceField
from apps.workforce.models import Skill, Team, Technician
from apps.workorders.forms import EquipmentChoiceField

from .models import PlanPart, PreventivePlan


class MeterChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.equipment.code} · {obj.name} ({obj.unit})"


class PreventivePlanForm(forms.ModelForm):
    equipment = EquipmentChoiceField(queryset=Equipment.objects.none(), label=_("Équipement"))
    meter = MeterChoiceField(queryset=Meter.objects.none(), required=False, label=_("Compteur"))
    checklist_text = forms.CharField(
        label=_("Check-list"), required=False, widget=forms.Textarea(attrs={"rows": 5}),
        help_text=_("Un point de contrôle par ligne. Copiée dans chaque OT généré."),
    )

    class Meta:
        model = PreventivePlan
        fields = [
            "code", "name", "equipment", "operations", "instructions", "estimated_hours", "priority",
            "team", "technicians", "skills",
            "trigger_mode", "period_value", "period_unit", "next_due_date", "schedule_basis", "lead_days",
            "meter", "meter_interval", "meter_lead", "last_done_meter", "is_active",
        ]
        widgets = {
            "operations": forms.Textarea(attrs={"rows": 3}),
            "instructions": forms.Textarea(attrs={"rows": 4}),
            "next_due_date": DateInput(),
            "technicians": forms.CheckboxSelectMultiple,
            "skills": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.exclude(status=Equipment.Status.RETIRED).order_by("code")
        self.fields["meter"].queryset = Meter.objects.select_related("equipment").order_by("equipment__code", "name")
        self.fields["team"].queryset = Team.objects.filter(is_active=True)
        self.fields["technicians"].queryset = Technician.objects.filter(is_active=True)
        self.fields["skills"].queryset = Skill.objects.all()
        if self.instance.pk:
            self.fields["checklist_text"].initial = "\n".join(self.instance.checklist.values_list("label", flat=True))

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        duplicates = PreventivePlan.objects.filter(code__iexact=code)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("Ce code est déjà utilisé dans votre entreprise."))
        return code

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("trigger_mode")
        meter = cleaned.get("meter")
        if mode in (PreventivePlan.TriggerMode.METER, PreventivePlan.TriggerMode.BOTH) and meter is not None:
            if cleaned.get("last_done_meter") is None:
                # Point de départ : la valeur actuelle du compteur.
                cleaned["last_done_meter"] = meter.current_value
                self.instance.last_done_meter = meter.current_value
        if mode == PreventivePlan.TriggerMode.CALENDAR:
            cleaned["meter"] = None
            self.instance.meter = None
        return cleaned

    def checklist_lines(self):
        text = self.cleaned_data.get("checklist_text") or ""
        return [line.strip()[:255] for line in text.splitlines() if line.strip()]


class PlanPartForm(forms.ModelForm):
    """Pièce prévue : un article du magasin (réservé à chaque OT) ou une pièce saisie librement."""

    stock_item = ItemReferenceField(label=_("Article du magasin"), required=False)

    class Meta:
        model = PlanPart
        fields = ["reference", "designation", "quantity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["designation"].required = False

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get("stock_item")
        if item is not None:
            cleaned["reference"], cleaned["designation"] = item.reference, item.designation[:200]
            self.instance.item = item
        elif not (cleaned.get("designation") or "").strip():
            raise forms.ValidationError(_("Choisissez un article du magasin ou saisissez la désignation de la pièce."))
        return cleaned


class PostponeForm(forms.Form):
    new_date = forms.DateField(label=_("Nouvelle date"), widget=DateInput())
    reason = forms.CharField(label=_("Motif du report"), max_length=200)
