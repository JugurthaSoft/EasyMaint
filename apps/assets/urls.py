from django.urls import path

from . import views

app_name = "assets"

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="equipment_list"),
    path("export.xlsx", views.EquipmentExportView.as_view(), name="equipment_export"),
    path("<int:pk>/fiche.pdf", views.equipment_pdf, name="equipment_pdf"),
    path("etiquettes-qr/", views.equipment_qr_labels, name="equipment_qr_labels"),
    path("nouveau/", views.EquipmentCreateView.as_view(), name="equipment_create"),
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="equipment_detail"),
    path("<int:pk>/modifier/", views.EquipmentUpdateView.as_view(), name="equipment_update"),
    path("<int:pk>/etat/", views.equipment_change_status, name="equipment_change_status"),
    path("<int:pk>/photo/", views.equipment_photo, name="equipment_photo"),
    path("<int:pk>/qr.svg", views.equipment_qr, name="equipment_qr"),
    path("<int:pk>/compteurs/nouveau/", views.MeterCreateView.as_view(), name="meter_create"),
    path("<int:pk>/documents/", views.attachment_upload, name="attachment_upload"),
    path("compteurs/<int:meter_pk>/releve/", views.reading_create, name="reading_create"),
    path("documents/<int:pk>/", views.attachment_download, name="attachment_download"),
    path("documents/<int:pk>/supprimer/", views.attachment_delete, name="attachment_delete"),
    path("q/<uuid:token>/", views.qr_resolve, name="qr_resolve"),
    path("localisations/", views.LocationTreeView.as_view(), name="location_tree"),
    path("localisations/nouvelle/", views.LocationCreateView.as_view(), name="location_create"),
    path("localisations/<int:pk>/", views.LocationUpdateView.as_view(), name="location_update"),
    path("referentiels/", views.ReferentialListView.as_view(), name="family_list"),
    path("referentiels/familles/nouvelle/", views.FamilyCreateView.as_view(), name="family_create"),
    path("referentiels/familles/<int:pk>/", views.FamilyUpdateView.as_view(), name="family_update"),
    path("referentiels/fabricants/nouveau/", views.ManufacturerCreateView.as_view(), name="manufacturer_create"),
    path("referentiels/fabricants/<int:pk>/", views.ManufacturerUpdateView.as_view(), name="manufacturer_update"),
]
