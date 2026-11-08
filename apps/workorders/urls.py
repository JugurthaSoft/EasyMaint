from django.urls import path

from . import views

app_name = "workorders"

urlpatterns = [
    path("demandes/", views.RequestListView.as_view(), name="request_list"),
    path("demandes/nouvelle/", views.RequestCreateView.as_view(), name="request_create"),
    path("demandes/<int:pk>/", views.RequestDetailView.as_view(), name="request_detail"),
    path("demandes/<int:pk>/<str:decision>/", views.request_decide, name="request_decide"),
    path("ot/", views.WorkOrderListView.as_view(), name="wo_list"),
    path("ot/nouveau/", views.WorkOrderCreateView.as_view(), name="wo_create"),
    path("ot/export.xlsx", views.wo_export, name="wo_export"),
    path("ot/<int:pk>/fiche.pdf", views.wo_pdf, name="wo_pdf"),
    path("mes-ot/", views.MyWorkOrdersView.as_view(), name="my_work_orders"),
    path("ot/<int:pk>/", views.WorkOrderDetailView.as_view(), name="wo_detail"),
    path("ot/<int:pk>/intervention/", views.WorkOrderExecuteView.as_view(), name="wo_execute"),
    path("ot/<int:pk>/planifier/", views.WorkOrderPlanView.as_view(), name="wo_plan"),
    path("ot/<int:pk>/action/<str:action>/", views.wo_action, name="wo_action"),
    path("ot/<int:pk>/compte-rendu/", views.wo_report, name="wo_report"),
    path("ot/<int:pk>/pieces/", views.wo_part_add, name="wo_part_add"),
    path("ot/<int:pk>/pieces/<int:item_pk>/supprimer/", views.wo_part_delete, name="wo_part_delete"),
    path("ot/<int:pk>/depenses/", views.wo_expense_add, name="wo_expense_add"),
    path("ot/<int:pk>/depenses/<int:item_pk>/supprimer/", views.wo_expense_delete, name="wo_expense_delete"),
    path("ot/<int:pk>/check-list/", views.wo_checklist_add, name="wo_checklist_add"),
    path("ot/<int:pk>/check-list/<int:item_pk>/", views.wo_checklist_toggle, name="wo_checklist_toggle"),
    path("ot/<int:pk>/temps/", views.wo_time_add, name="wo_time_add"),
    path("ot/<int:pk>/temps/<int:item_pk>/supprimer/", views.wo_time_delete, name="wo_time_delete"),
    path("ot/<int:pk>/fichiers/", views.wo_attachment_upload, name="wo_attachment_upload"),
    path("ot/fichiers/<int:pk>/", views.wo_attachment_file, name="wo_attachment_file"),
    path("codes-defaillance/", views.FailureCodeListView.as_view(), name="failure_codes"),
    path("codes-defaillance/nouveau/", views.FailureCodeCreateView.as_view(), name="failure_code_create"),
    path("codes-defaillance/<int:pk>/", views.FailureCodeUpdateView.as_view(), name="failure_code_update"),
]
