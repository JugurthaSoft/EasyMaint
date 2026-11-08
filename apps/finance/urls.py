from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.CostsView.as_view(), name="costs"),
    path("export/", views.costs_export, name="costs_export"),
    path("rapport.pdf", views.costs_pdf, name="costs_pdf"),
    path("budget/", views.BudgetView.as_view(), name="budget"),
    path("budget/rapport.pdf", views.budget_pdf, name="budget_pdf"),
    path("budget/<int:year>/<int:unit_pk>/", views.budget_edit, name="budget_edit"),
]
