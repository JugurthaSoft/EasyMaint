from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext
from rest_framework import serializers

from ..models import Equipment, EquipmentFamily, Location, Manufacturer, Meter


class TenantRelatedField(serializers.PrimaryKeyRelatedField):
    """
    Clé étrangère limitée à l'entreprise courante. Le queryset est recalculé à
    chaque requête (un queryset défini au chargement du module serait vide).
    """

    def __init__(self, model, **kwargs):
        self.model = model
        super().__init__(**kwargs)

    def get_queryset(self):
        return self.model.objects.all()


class _CleanOnValidateMixin:
    """Applique les règles métier du modèle (clean) aux écritures API."""

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance or self.Meta.model()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as error:
            raise serializers.ValidationError(getattr(error, "message_dict", {"non_field_errors": error.messages}))
        return attrs


class LocationSerializer(_CleanOnValidateMixin, serializers.ModelSerializer):
    parent = TenantRelatedField(Location, allow_null=True, required=False)
    full_path = serializers.CharField(read_only=True)

    class Meta:
        model = Location
        fields = ["id", "code", "name", "kind", "parent", "is_active", "full_path"]


class EquipmentFamilySerializer(serializers.ModelSerializer):
    parent = TenantRelatedField(EquipmentFamily, allow_null=True, required=False)

    class Meta:
        model = EquipmentFamily
        fields = ["id", "code", "name", "parent", "is_active"]


class ManufacturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Manufacturer
        fields = ["id", "name", "website", "phone", "email"]


class MeterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Meter
        fields = ["id", "name", "kind", "unit", "is_cumulative", "current_value", "last_reading_at"]
        read_only_fields = ["current_value", "last_reading_at"]


class EquipmentSerializer(_CleanOnValidateMixin, serializers.ModelSerializer):
    family = TenantRelatedField(EquipmentFamily)
    location = TenantRelatedField(Location)
    manufacturer = TenantRelatedField(Manufacturer, allow_null=True, required=False)
    parent = TenantRelatedField(Equipment, allow_null=True, required=False)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    required_hours_per_day = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=Decimal("0"), max_value=Decimal("24"), required=False,
    )
    meters = MeterSerializer(many=True, read_only=True)

    class Meta:
        model = Equipment
        fields = [
            "id", "code", "designation", "family", "location", "parent", "status", "status_label",
            "criticality", "manufacturer", "brand", "model", "serial_number", "commissioning_date",
            "required_hours_per_day", "notes", "meters",
        ]

    def validate_code(self, value):
        value = value.strip().upper()
        duplicates = Equipment.objects.filter(code=value)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(gettext("Ce code est déjà utilisé."))
        return value
