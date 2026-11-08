from rest_framework.routers import DefaultRouter

from .views import (
    EquipmentFamilyViewSet,
    EquipmentViewSet,
    LocationViewSet,
    ManufacturerViewSet,
)

router = DefaultRouter()
router.register("equipements", EquipmentViewSet, basename="api-equipment")
router.register("localisations", LocationViewSet, basename="api-location")
router.register("familles", EquipmentFamilyViewSet, basename="api-family")
router.register("fabricants", ManufacturerViewSet, basename="api-manufacturer")

urlpatterns = router.urls
