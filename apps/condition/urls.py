from django.urls import path

from . import views, views_imports

app_name = "condition"

urlpatterns = [
    path("", views.OverviewView.as_view(), name="overview"),
    path("parametres/", views.ParameterListView.as_view(), name="parameter_list"),
    path("parametres/nouveau/", views.ParameterCreateView.as_view(), name="parameter_create"),
    path("parametres/<int:pk>/", views.ParameterUpdateView.as_view(), name="parameter_update"),
    path("equipement/<int:equipment_pk>/points/nouveau/", views.PointCreateView.as_view(), name="point_create"),
    path("equipement/<int:equipment_pk>/mesures/", views.SessionCreateView.as_view(), name="session_create"),
    path("points/<int:pk>/", views.PointDetailView.as_view(), name="point_detail"),
    path("points/<int:pk>/modifier/", views.PointUpdateView.as_view(), name="point_update"),
    path("points/<int:pk>/photo/", views.point_photo, name="point_photo"),
    path("points/<int:pk>/seuils/<int:parameter_pk>/", views.threshold_save, name="threshold_save"),
    path("tournees/", views.SessionListView.as_view(), name="session_list"),
    path("tournees/<int:pk>/", views.SessionDetailView.as_view(), name="session_detail"),
    path("tournees/fichiers/<int:pk>/", views.session_attachment, name="session_attachment"),
    path("alertes/", views.AlertListView.as_view(), name="alert_list"),
    path("alertes/<int:pk>/", views.AlertDetailView.as_view(), name="alert_detail"),
    path("alertes/<int:pk>/<str:action>/", views.alert_action, name="alert_action"),
    path("regles/", views.RuleListView.as_view(), name="rule_list"),
    path("regles/nouvelle/", views.RuleCreateView.as_view(), name="rule_create"),
    path("regles/<int:pk>/", views.RuleUpdateView.as_view(), name="rule_update"),
    path("imports/", views_imports.ImportListView.as_view(), name="import_list"),
    path("imports/modele/", views_imports.import_template, name="import_template"),
    path("imports/formats/<int:pk>/supprimer/", views_imports.profile_delete, name="profile_delete"),
    path("imports/<int:pk>/", views_imports.ImportDetailView.as_view(), name="import_detail"),
    path("imports/<int:pk>/correspondance/", views_imports.import_mapping, name="import_mapping"),
    path("imports/<int:pk>/confirmer/", views_imports.import_confirm, name="import_confirm"),
    path("imports/<int:pk>/abandonner/", views_imports.import_cancel, name="import_cancel"),
    path("imports/<int:pk>/fichier/", views_imports.import_file, name="import_file"),
]
