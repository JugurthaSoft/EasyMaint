"""Coûts réels, regroupements, budget par unité, rapports Excel et PDF, droits et isolation."""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.assets.models import Equipment, EquipmentFamily, Location
from apps.core.tenancy import tenant_context
from apps.finance import selectors
from apps.finance.forms import BudgetForm
from apps.finance.models import Budget
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder
from conftest import make_user

D = Decimal


def at(day):
    return timezone.make_aware(datetime.combine(day, time(15, 0)))


@pytest.fixture
def costs_a(tenant_a, equipment_a, admin_a):
    year = timezone.localdate().year
    with tenant_context(tenant_a):
        site = Location.objects.get(code="SITE")
        unit = Location.objects.create(code="INJ", name="Unité injection", kind="workshop", parent=site)
        line = Location.objects.create(code="L1", name="Ligne 1", kind="line", parent=unit)
        parent_family = EquipmentFamily.objects.create(code="PRESSES", name="Presses")
        sub_family = EquipmentFamily.objects.create(code="INJ", name="Presses à injecter", parent=parent_family)
        press = Equipment.objects.create(code="PRS-INJ", designation="Presse 350 t", family=sub_family, location=line)

        def order(equipment, kind, finished, status="validated", **costs):
            wo = wo_services.create_work_order(user=admin_a, equipment=equipment, title=f"OT {kind}", kind=kind, priority=2)
            values = {"labour_cost": D("0"), "parts_cost": D("0"), "external_cost": D("0"), "other_cost": D("0")} | costs
            values["total_cost"] = sum(values.values(), D("0"))
            WorkOrder.objects.filter(pk=wo.pk).update(status=status, finished_at=at(finished), validated_at=at(finished), **values)
            return WorkOrder.all_tenants.get(pk=wo.pk)

        march, april = date(year, 3, 10), date(year, 4, 30)
        orders = {
            "corr": order(press, "corrective", march, labour_cost=D("100"), parts_cost=D("250")),
            "prev": order(press, "preventive", april, labour_cost=D("60"), external_cost=D("40")),
            "site": order(equipment_a, "corrective", april, other_cost=D("30")),  # équipement hors unité
            "old": order(press, "corrective", date(year - 1, 6, 1), labour_cost=D("999")),
            "open": order(press, "corrective", april, status="done", labour_cost=D("500")),  # non validé : exclu
        }
        from apps.inventory import services as stock
        from apps.inventory.models import Item, Warehouse

        warehouse = Warehouse.objects.create(code="MAG", name="Magasin")
        item = Item.objects.create(reference="GR-1", designation="Graisse")
        stock.receive(item=item, warehouse=warehouse, quantity=10, unit_cost=D("5"), user=admin_a, moved_at=at(date(year, 1, 5)))
        stock.issue(item=item, warehouse=warehouse, quantity=2, user=admin_a, reason="Graissage", equipment=press, moved_at=at(march))
    return {"tenant": tenant_a, "unit": unit, "press": press, "family": parent_family, "orders": orders, "year": year,
            "admin": admin_a, "site_equipment": equipment_a}


@pytest.mark.django_db
def test_records_use_validated_orders_and_stock_issues(costs_a):
    s = costs_a
    with tenant_context(s["tenant"]):
        records = selectors.cost_records(date(s["year"], 1, 1), date(s["year"], 12, 31))
        refs = {r.reference for r in records}
        assert s["orders"]["corr"].number in refs and s["orders"]["prev"].number in refs
        assert s["orders"]["old"].number not in refs and s["orders"]["open"].number not in refs
        stock = [r for r in records if r.kind == selectors.STOCK_KIND]
        assert len(stock) == 1 and stock[0].parts == D("10.000") and stock[0].unit_id == s["unit"].pk
        total = selectors.totals(records)
        assert total["total"] == D("490") and total["count"] == 3
        press_record = next(r for r in records if r.reference == s["orders"]["corr"].number)
        assert press_record.unit_id == s["unit"].pk and press_record.family_id == s["family"].pk  # unité et famille racine


@pytest.mark.django_db
def test_grouping_and_filters(costs_a):
    s = costs_a
    with tenant_context(s["tenant"]):
        records = selectors.cost_records(date(s["year"], 1, 1), date(s["year"], 12, 31))
        by_unit = {str(row["label"]): row["total"] for row in selectors.group(records, "unite")}
        assert by_unit == {"Unité injection": D("460"), "Hors unité": D("30")}
        by_kind = {row["key"]: row["total"] for row in selectors.group(records, "type")}
        assert by_kind == {"corrective": D("380"), "preventive": D("100"), "stock": D("10")}
        months = selectors.group(records, "mois")
        assert [row["key"] for row in months] == [(s["year"], 3), (s["year"], 4)]
        assert abs(sum(row["share"] for row in months) - D("100")) < D("0.0001")
        only_press = selectors.cost_records(date(s["year"], 1, 1), date(s["year"], 12, 31), equipment=s["press"], kind="corrective")
        assert selectors.totals(only_press)["total"] == D("350")
        only_unit = selectors.cost_records(date(s["year"], 4, 1), date(s["year"], 4, 30), unit=s["unit"])
        assert selectors.totals(only_unit)["total"] == D("100")


@pytest.mark.django_db
def test_budget_equal_split_and_budget_vs_actual(costs_a):
    s = costs_a
    with tenant_context(s["tenant"]):
        form = BudgetForm({"annual": "12000.010", "split": "on"}, instance=Budget(year=s["year"], unit=s["unit"]))
        assert form.is_valid(), form.errors
        budget = form.save()
        assert budget.month_01 == D("1000.000") and budget.month_12 == D("1000.010") and budget.annual == D("12000.010")
        rows, total = selectors.budget_table(s["year"])
        unit_row = next(row for row in rows if row["unit"] == s["unit"])
        assert unit_row["actual"][2] == D("360") and unit_row["actual"][3] == D("100")
        assert unit_row["actual_total"] == D("460") and round(unit_row["rate"], 2) == D("3.83")
        assert total["actual_total"] == D("490")  # « Hors unité » compris
        bad = BudgetForm({"month_01": "-5"}, instance=Budget(year=s["year"], unit=s["unit"]))
        assert not bad.is_valid()


@pytest.mark.django_db
def test_screens_exports_and_pdf(client, costs_a):
    s = costs_a
    client.force_login(s["admin"])
    year = s["year"]
    for by in ("equipement", "unite", "famille", "type", "mois"):
        response = client.get(reverse("finance:costs") + f"?du={year}-01-01&au={year}-12-31&regroupement={by}")
        assert response.status_code == 200, by
    page = client.get(reverse("finance:costs") + f"?du={year}-01-01&au={year}-12-31&regroupement=unite").content.decode()
    assert "Unité injection" in page and "Hors unité" in page
    excel = client.get(reverse("finance:costs_export") + f"?du={year}-01-01&au={year}-12-31")
    assert excel.status_code == 200 and excel["Content-Type"].startswith("application/vnd.openxml")
    pdf = client.get(reverse("finance:costs_pdf") + f"?du={year}-01-01&au={year}-12-31&regroupement=type")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client.get(reverse("finance:budget") + f"?annee={year}").status_code == 200
    budget_pdf = client.get(reverse("finance:budget_pdf") + f"?annee={year}")
    assert budget_pdf.status_code == 200 and budget_pdf.content.startswith(b"%PDF")
    edit = reverse("finance:budget_edit", args=[year, s["unit"].pk])
    assert client.get(edit).status_code == 200
    assert client.post(edit, {"annual": "6000", "split": "on"}).status_code == 302
    with tenant_context(s["tenant"]):
        assert Budget.objects.get(year=year, unit=s["unit"]).annual == D("6000")
    site = Location.all_tenants.get(code="SITE", tenant=s["tenant"])
    assert client.get(reverse("finance:budget_edit", args=[year, site.pk])).status_code == 404  # pas une unité
    assert client.get(s["press"].get_absolute_url() + "?onglet=couts").status_code == 200
    assert "Dépensé depuis le 1er janvier" in client.get(reverse("dashboard:home")).content.decode()


@pytest.mark.django_db
def test_rights_and_isolation(client, costs_a, tenant_a, admin_b):
    s = costs_a
    technician = make_user(tenant_a, "technician", "tech_couts")
    client.force_login(technician)
    assert client.get(reverse("finance:costs")).status_code == 403
    assert client.get(reverse("finance:costs_pdf")).status_code == 403
    production = make_user(tenant_a, "production_manager", "prod_couts")
    client.force_login(production)
    assert client.get(reverse("finance:costs")).status_code == 200
    assert client.get(reverse("finance:budget_edit", args=[s["year"], s["unit"].pk])).status_code == 403
    client.force_login(admin_b)
    response = client.get(reverse("finance:costs") + f"?du={s['year']}-01-01&au={s['year']}-12-31")
    assert response.status_code == 200 and response.context["total"]["total"] == 0
    assert client.get(reverse("finance:budget_edit", args=[s["year"], s["unit"].pk])).status_code == 404
