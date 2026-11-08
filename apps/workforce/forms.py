from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.core.tenancy import get_current_tenant

from .models import Contractor, Skill, Team, Technician


def _unique(form, value, **lookup):
    duplicates = form._meta.model.objects.filter(**lookup)
    if form.instance.pk:
        duplicates = duplicates.exclude(pk=form.instance.pk)
    if duplicates.exists():
        raise forms.ValidationError(_("Cette valeur est déjà utilisée dans votre entreprise."))
    return value


class TechnicianForm(forms.ModelForm):
    class Meta:
        model = Technician
        fields = [
            "employee_number", "first_name", "last_name", "function", "specialty", "team", "skills",
            "phone", "email", "hourly_rate", "overtime_rate", "user", "is_active",
        ]
        widgets = {"skills": forms.CheckboxSelectMultiple}
        help_texts = {"user": _("Relier un compte permet au technicien d'exécuter ses OT depuis son téléphone.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = Team.objects.filter(is_active=True)
        self.fields["skills"].queryset = Skill.objects.all()
        taken = Technician.objects.exclude(pk=self.instance.pk).exclude(user__isnull=True).values_list("user_id", flat=True)
        self.fields["user"].queryset = User.objects.filter(tenant=get_current_tenant(), is_active=True).exclude(pk__in=list(taken))

    def clean_employee_number(self):
        number = self.cleaned_data["employee_number"].strip().upper()
        return _unique(self, number, employee_number__iexact=number)


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "leader", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leader"].queryset = Technician.objects.filter(is_active=True)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        return _unique(self, name, name__iexact=name)


class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ["code", "name"]

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return _unique(self, code, code__iexact=code)


class ContractorForm(forms.ModelForm):
    class Meta:
        model = Contractor
        fields = ["name", "contact_name", "phone", "email", "specialties", "hourly_rate", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        return _unique(self, name, name__iexact=name)
