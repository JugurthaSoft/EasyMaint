from django.urls import path

from . import views

app_name = "workforce"

urlpatterns = [
    path("", views.TechnicianListView.as_view(), name="technician_list"),
    path("techniciens/nouveau/", views.TechnicianCreateView.as_view(), name="technician_create"),
    path("techniciens/<int:pk>/", views.TechnicianUpdateView.as_view(), name="technician_update"),
    path("equipes/nouvelle/", views.TeamCreateView.as_view(), name="team_create"),
    path("equipes/<int:pk>/", views.TeamUpdateView.as_view(), name="team_update"),
    path("referentiels/", views.ReferentialView.as_view(), name="referentials"),
    path("competences/nouvelle/", views.SkillCreateView.as_view(), name="skill_create"),
    path("competences/<int:pk>/", views.SkillUpdateView.as_view(), name="skill_update"),
    path("sous-traitants/nouveau/", views.ContractorCreateView.as_view(), name="contractor_create"),
    path("sous-traitants/<int:pk>/", views.ContractorUpdateView.as_view(), name="contractor_update"),
]
