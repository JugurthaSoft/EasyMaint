from datetime import timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.forms import DateInput, DateTimeInput
from apps.assets.models import Equipment
from apps.workforce.models import Contractor, Team, Technician

from .models import ChecklistItem, Expense, FailureCode, PartUsage, Priority, WorkOrder


class EquipmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.code} · {obj.designation}"


def _active_equipment():
    return Equipment.objects.exclude(status=Equipment.Status.RETIRED).order_by("code")


class WorkRequestForm(forms.Form):
    """Déclaration d'une panne : volontairement courte (opérateur, chef de ligne)."""

    equipment = EquipmentChoiceField(queryset=Equipment.objects.none(), label=_("Équipement"))
    description = forms.CharField(
        label=_("Description du problème"), widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Ce qui se passe, depuis quand, ce qui a été constaté."),
    )
    priority = forms.TypedChoiceField(label=_("Priorité"), choices=Priority.choices, coerce=int, initial=Priority.NORMAL)
    production_stopped = forms.BooleanField(label=_("La production est arrêtée"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = _active_equipment()


class WorkOrderCreateForm(forms.ModelForm):
    equipment = EquipmentChoiceField(queryset=Equipment.objects.none(), label=_("Équipement"))

    class Meta:
        model = WorkOrder
        fields = [
            "equipment", "kind", "title", "description", "priority", "production_stopped",
            "planned_date", "due_date", "estimated_hours", "team", "technicians", "contractor",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "planned_date": DateInput(), "due_date": DateInput(),
            "technicians": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, simple=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = _active_equipment()
        self.fields["team"].queryset = Team.objects.filter(is_active=True)
        self.fields["technicians"].queryset = Technician.objects.filter(is_active=True)
        self.fields["contractor"].queryset = Contractor.objects.filter(is_active=True)
        if simple:
            # Technicien : création d'un OT urgent sans les champs de planification.
            for name in ("planned_date", "due_date", "estimated_hours", "team", "technicians", "contractor", "kind"):
                self.fields.pop(name)

    def clean(self):
        cleaned = super().clean()
        planned, due = cleaned.get("planned_date"), cleaned.get("due_date")
        if planned and due and due < planned:
            self.add_error("due_date", _("L'échéance ne peut pas précéder la date prévue."))
        return cleaned


class PlanningForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = ["title", "description", "kind", "priority", "planned_date", "due_date", "estimated_hours", "team", "technicians", "contractor"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "planned_date": DateInput(), "due_date": DateInput(),
            "technicians": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = Team.objects.filter(is_active=True)
        self.fields["technicians"].queryset = Technician.objects.filter(is_active=True)
        self.fields["contractor"].queryset = Contractor.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        planned, due = cleaned.get("planned_date"), cleaned.get("due_date")
        if planned and due and due < planned:
            self.add_error("due_date", _("L'échéance ne peut pas précéder la date prévue."))
        return cleaned


class ReportForm(forms.ModelForm):
    """Compte rendu du technicien : diagnostic, codes de défaillance, travaux réalisés."""

    class Meta:
        model = WorkOrder
        fields = ["diagnosis", "failure_mode", "failure_cause", "work_done"]
        widgets = {"diagnosis": forms.Textarea(attrs={"rows": 3}), "work_done": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["failure_mode"].queryset = FailureCode.objects.filter(kind=FailureCode.Kind.MODE, is_active=True)
        self.fields["failure_cause"].queryset = FailureCode.objects.filter(kind=FailureCode.Kind.CAUSE, is_active=True)
        self.fields["failure_mode"].empty_label = _("Choisir…")
        self.fields["failure_cause"].empty_label = _("Choisir…")


class PartForm(forms.ModelForm):
    class Meta:
        model = PartUsage
        fields = ["reference", "designation", "quantity", "unit_cost"]


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["nature", "label", "supplier", "amount"]


class ChecklistItemForm(forms.ModelForm):
    class Meta:
        model = ChecklistItem
        fields = ["label"]


class TimeEntryForm(forms.Form):
    technician = forms.ModelChoiceField(queryset=Technician.objects.none(), label=_("Technicien"))
    started_at = forms.DateTimeField(label=_("Début"), widget=DateTimeInput())
    ended_at = forms.DateTimeField(label=_("Fin"), widget=DateTimeInput())
    is_overtime = forms.BooleanField(label=_("Heures supplémentaires"), required=False)
    note = forms.CharField(label=_("Commentaire"), max_length=200, required=False)

    def __init__(self, *args, technicians=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["technician"].queryset = technicians if technicians is not None else Technician.objects.filter(is_active=True)
        if not self.is_bound:
            now = timezone.localtime().replace(second=0, microsecond=0)
            self.initial.setdefault("ended_at", now)
            self.initial.setdefault("started_at", now - timedelta(hours=1))


class FailureCodeForm(forms.ModelForm):
    class Meta:
        model = FailureCode
        fields = ["kind", "code", "name", "is_active"]

    def clean(self):
        cleaned = super().clean()
        code, kind = (cleaned.get("code") or "").strip().upper(), cleaned.get("kind")
        if code and kind:
            cleaned["code"] = code
            duplicates = FailureCode.objects.filter(kind=kind, code__iexact=code)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error("code", _("Ce code existe déjà pour ce type."))
        return cleaned
