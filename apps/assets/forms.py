"""
Formulaires du patrimoine.

Les listes de choix (localisations, familles, utilisateurs...) sont construites
dans __init__, au moment de la requête : c'est ce qui garantit qu'elles ne
contiennent que les données de l'entreprise courante.
"""
from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.core.models import Attachment
from apps.core.tenancy import get_current_tenant

from .models import Equipment, EquipmentFamily, Location, Manufacturer, Meter
from .selectors import descendant_location_ids, location_paths


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


def _ensure_unique(form, field, value, **lookup):
    """Contrôle explicite d'unicité dans l'entreprise courante, avec un message clair."""
    duplicates = form._meta.model.objects.filter(**lookup)
    if form.instance.pk:
        duplicates = duplicates.exclude(pk=form.instance.pk)
    if duplicates.exists():
        raise forms.ValidationError(_("Cette valeur est déjà utilisée dans votre entreprise."))
    return value


class LocationChoiceField(forms.ModelChoiceField):
    """Affiche le chemin complet (Usine › Unité › Ligne) au lieu du seul nom."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paths = None

    def label_from_instance(self, obj):
        if self._paths is None:
            self._paths = location_paths()
        return self._paths.get(obj.pk, obj.name)


class EquipmentForm(forms.ModelForm):
    location = LocationChoiceField(queryset=Location.objects.none(), label=_("Localisation"))

    class Meta:
        model = Equipment
        fields = [
            "code", "designation", "family", "location", "parent", "status", "criticality",
            "manufacturer", "brand", "model", "serial_number", "commissioning_date",
            "responsible", "required_hours_per_day", "operating_days_per_week", "photo", "notes",
        ]
        widgets = {
            "commissioning_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            # Champ fichier simple : la photo actuelle est affichée sur la fiche, via une vue protégée.
            "photo": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_location = self.instance.location_id if self.instance.pk else None
        # Les localisations désactivées restent proposées si l'équipement y est déjà.
        self.fields["location"].queryset = Location.objects.filter(Q(is_active=True) | Q(pk=current_location))
        self.fields["family"].queryset = EquipmentFamily.objects.filter(is_active=True).select_related("parent")
        self.fields["manufacturer"].queryset = Manufacturer.objects.all()
        parents = Equipment.objects.exclude(status=Equipment.Status.RETIRED)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["responsible"].queryset = User.objects.filter(tenant=get_current_tenant(), is_active=True)
        self.fields["code"].widget.attrs.update({"autocomplete": "off", "style": "text-transform: uppercase"})
        self.fields["operating_days_per_week"].required = False

    def clean_operating_days_per_week(self):
        """Champ facultatif à la saisie : à défaut, la valeur actuelle de l'équipement (6 jours pour un nouveau)."""
        value = self.cleaned_data.get("operating_days_per_week")
        return value if value is not None else (self.instance.operating_days_per_week or 6)

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return _ensure_unique(self, "code", code, code__iexact=code)


class MeterForm(forms.ModelForm):
    class Meta:
        model = Meter
        fields = ["name", "kind", "unit", "is_cumulative"]
        help_texts = {"unit": _("Laisser vide pour l'unité par défaut (h, cycles, km).")}

    def __init__(self, *args, equipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.equipment = equipment

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.equipment and self.equipment.meters.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Cet équipement a déjà un compteur portant ce nom."))
        return name


class ReadingForm(forms.Form):
    value = forms.DecimalField(label=_("Valeur relevée"), max_digits=14, decimal_places=2, min_value=0)
    reading_at = forms.DateTimeField(label=_("Date du relevé"), widget=DateTimeInput())
    note = forms.CharField(label=_("Commentaire"), max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("reading_at", timezone.localtime().replace(second=0, microsecond=0))


class LocationForm(forms.ModelForm):
    parent = LocationChoiceField(queryset=Location.objects.none(), required=False, label=_("Localisation parente"))

    class Meta:
        model = Location
        fields = ["code", "name", "kind", "parent", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        excluded = descendant_location_ids(self.instance.pk) if self.instance.pk else []
        self.fields["parent"].queryset = Location.objects.exclude(pk__in=excluded)
        self.fields["parent"].empty_label = _("— Aucune (niveau racine) —")

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return _ensure_unique(self, "code", code, code__iexact=code)


class EquipmentFamilyForm(forms.ModelForm):
    class Meta:
        model = EquipmentFamily
        fields = ["code", "name", "parent", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parents = EquipmentFamily.objects.filter(parent__isnull=True)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["parent"].empty_label = _("— Aucune (famille principale) —")

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        return _ensure_unique(self, "code", code, code__iexact=code)


class ManufacturerForm(forms.ModelForm):
    # Une adresse saisie sans préfixe est complétée en https://
    website = forms.URLField(label=_("Site web"), required=False, assume_scheme="https")

    class Meta:
        model = Manufacturer
        fields = ["name", "website", "phone", "email", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        return _ensure_unique(self, "name", name, name__iexact=name)


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file", "title", "category"]
