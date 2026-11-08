from django.urls import path

from . import views

app_name = "preventive"

urlpatterns = [
    path("", views.PlanListView.as_view(), name="plan_list"),
    path("nouveau/", views.PlanCreateView.as_view(), name="plan_create"),
    path("<int:pk>/", views.PlanDetailView.as_view(), name="plan_detail"),
    path("<int:pk>/modifier/", views.PlanUpdateView.as_view(), name="plan_update"),
    path("<int:pk>/generer/", views.plan_generate, name="plan_generate"),
    path("<int:pk>/pieces/", views.plan_part_add, name="plan_part_add"),
    path("<int:pk>/pieces/<int:item_pk>/supprimer/", views.plan_part_delete, name="plan_part_delete"),
    path("<int:pk>/documents/", views.plan_attachment_upload, name="plan_attachment_upload"),
    path("documents/<int:pk>/", views.plan_attachment_file, name="plan_attachment_file"),
    path("planning/", views.PlanningView.as_view(), name="planning"),
    path("ot/<int:pk>/reporter/", views.work_order_postpone, name="wo_postpone"),
]
