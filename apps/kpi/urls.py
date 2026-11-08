from django.urls import path

from . import views

app_name = "kpi"

urlpatterns = [
    path("", views.KpiView.as_view(), name="indicators"),
    path("definitions/", views.DefinitionsView.as_view(), name="definitions"),
    path("export/", views.kpi_export, name="export"),
    path("rapport.pdf", views.kpi_pdf, name="pdf"),
    path("rapports-mensuels/", views.ReportListView.as_view(), name="reports"),
    path("rapports-mensuels/produire/", views.report_generate, name="report_generate"),
    path("rapports-mensuels/<int:pk>/", views.report_file, name="report_file"),
]
