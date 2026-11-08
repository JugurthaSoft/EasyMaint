from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("tout-lu/", views.notification_read_all, name="read_all"),
    path("<int:pk>/", views.notification_open, name="open"),
]
