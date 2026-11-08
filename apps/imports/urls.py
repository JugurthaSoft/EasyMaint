from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.home, name="home"),
    path("modele/<str:kind>/", views.template, name="template"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/confirmer/", views.confirm, name="confirm"),
    path("<int:pk>/abandonner/", views.cancel, name="cancel"),
    path("<int:pk>/fichier/", views.original, name="original"),
]
