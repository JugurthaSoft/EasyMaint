from rest_framework import viewsets

from apps.accounts.permissions import HasCapability
from apps.core.api import TenantAPIMixin
from apps.core.models import AuditLog
from apps.core.services import log_action

from .. import selectors
from ..models import Equipment, EquipmentFamily, Location, Manufacturer
from .serializers import (
    EquipmentFamilySerializer,
    EquipmentSerializer,
    LocationSerializer,
    ManufacturerSerializer,
)


class _TenantViewSet(TenantAPIMixin, viewsets.ModelViewSet):
    """Base des ressources API : entreprise courante uniquement, droits par capacité, journal."""

    permission_classes = [HasCapability]
    read_capability = "assets.view"
    write_capability = "assets.manage"
    http_method_names = ["get", "post", "put", "patch", "head", "options"]  # pas de suppression via l'API

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        log_action(AuditLog.Action.CREATE, request=self.request, obj=instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        log_action(AuditLog.Action.UPDATE, request=self.request, obj=instance, changes={"API": ["", "modification via l'API"]})


class LocationViewSet(_TenantViewSet):
    serializer_class = LocationSerializer

    def get_queryset(self):
        return Location.objects.select_related("parent").order_by("name")


class EquipmentFamilyViewSet(_TenantViewSet):
    serializer_class = EquipmentFamilySerializer

    def get_queryset(self):
        return EquipmentFamily.objects.order_by("name")


class ManufacturerViewSet(_TenantViewSet):
    serializer_class = ManufacturerSerializer

    def get_queryset(self):
        return Manufacturer.objects.order_by("name")


class EquipmentViewSet(_TenantViewSet):
    serializer_class = EquipmentSerializer

    def get_queryset(self):
        if self.action == "list":
            return selectors.filter_equipment(self.request.query_params).prefetch_related("meters")
        # Lecture ou modification d'un équipement précis : y compris les équipements réformés.
        return Equipment.objects.prefetch_related("meters")


