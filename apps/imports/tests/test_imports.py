"""Imports de mise en service, documents PDF, export des OT, rapport mensuel."""
import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from apps.assets.models import Equipment, EquipmentFamily, Location
from apps.core.tenancy import tenant_context
from apps.imports.importers import IMPORTERS
from apps.imports.models import DataImport
from apps.workorders.models import Downtime, WorkOrder
from conftest import make_user

D = Decimal


def xlsx(rows, name="import.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def upload(client, kind, rows, **extra):
    response = client.post(reverse("imports:home"), {"kind": kind, "file": xlsx(rows), **extra})
    assert response.status_code == 302, response.content.decode()[:500]
    return response["Location"]


@pytest.mark.django_db
def test_templates_download_and_are_recognised(client, admin_a):
    client.force_login(admin_a)
    assert client.get(reverse("imports:home")).status_code == 200
    for kind, importer_class in IMPORTERS.items():
        response = client.get(reverse("imports:template", args=[kind]))
        assert response.status_code == 200
        headers = [c.value for c in load_workbook(io.BytesIO(response.content))["Données"][1]]
        importer = importer_class()
        assert set(importer.column_map(headers)) == {f.key for f in importer.fields}, kind


@pytest.mark.django_db
def test_equipment_import_with_preview_errors_and_update(client, admin_a, tenant_a, equipment_a):
    client.force_login(admin_a)
    header = ["Code", "Désignation", "Famille", "Localisation", "Équipement parent", "Fabricant", "Criticité", "Jours par semaine"]
    url = upload(client, "equipements", [
        header,
        ["cmp-10", "Compresseur 10", "COMP", "SITE", "", "Atlas Copco", "A", 7],
        ["CMP-10-SEC", "Sécheur", "COMP", "Usine", "CMP-10", "", "", ""],
        ["PRS-A1", "Presse renommée", "FAM", "SITE", "", "", "", ""],      # existe : ignorée
        ["X-1", "Inconnu", "FAM", "NULLE-PART", "", "", "Z", 9],          # refusée
    ])
    page = client.get(url)
    assert page.context["creates"] == 2 and page.context["skips"] == 1 and len(page.context["error_rows"]) == 1
    imp_pk = int(url.rstrip("/").split("/")[-1])
    client.post(reverse("imports:confirm", args=[imp_pk]))
    with tenant_context(tenant_a):
        compressor = Equipment.objects.get(code="CMP-10")
        dryer = Equipment.objects.get(code="CMP-10-SEC")
        assert compressor.criticality == "A" and compressor.operating_days_per_week == 7 and compressor.manufacturer.name == "Atlas Copco"
        assert dryer.parent == compressor and dryer.family == EquipmentFamily.objects.get(code="COMP")
        assert DataImport.objects.get(pk=imp_pk).created_count == 2
        assert Equipment.objects.get(code="PRS-A1").designation == "Machine PRS-A1"
    url = upload(client, "equipements", [header, ["PRS-A1", "Presse renommée", "FAM", "SITE", "", "", "", ""]], update_existing="on")
    client.post(reverse("imports:confirm", args=[int(url.rstrip("/").split("/")[-1])]))
    with tenant_context(tenant_a):
        assert Equipment.objects.get(code="PRS-A1").designation == "Presse renommée"


@pytest.mark.django_db
def test_supplier_and_item_import_with_initial_stock(client, admin_a, tenant_a):
    from apps.inventory import services
    from apps.inventory.models import Item, ItemSupplier, Warehouse

    client.force_login(admin_a)
    with tenant_context(tenant_a):
        warehouse = Warehouse.objects.create(code="MAG-C", name="Central")
    url = upload(client, "fournisseurs", [["Code", "Raison sociale", "E-mail"], ["RTS", "Roulements du Sahel", "contact@rts.tn"],
                                          ["BAD", "Mauvais mail", "pas-un-mail"]])
    client.post(reverse("imports:confirm", args=[int(url.rstrip("/").split("/")[-1])]))
    url = upload(client, "articles", [
        ["Référence", "Désignation", "Famille", "Unité", "Prix d'achat", "Stock mini", "Stock maxi", "Pièce critique", "Magasin", "Stock initial", "Emplacement", "Fournisseur"],
        ["rou-6205", "Roulement 6205", "ROUL", "pièce", "18,5", 4, 12, "oui", "MAG-C", 10, "A-03", "RTS"],
        ["HUILE-46", "Huile HLP 46", "LUB", "litre", 8.7, 100, 400, "non", "", "", "", ""],
        ["X", "Unité inconnue", "", "tonneau", "", "", "", "", "", 5, "", "INCONNU"],
    ])
    page = client.get(url)
    assert page.context["creates"] == 2 and len(page.context["error_rows"]) == 1
    client.post(reverse("imports:confirm", args=[int(url.rstrip("/").split("/")[-1])]))
    with tenant_context(tenant_a):
        bearing = Item.objects.get(reference="ROU-6205")
        assert bearing.is_critical and bearing.min_stock == D("4") and bearing.average_cost == D("18.5000")
        assert services.physical_quantity(bearing, warehouse) == D("10")
        assert ItemSupplier.objects.get(item=bearing).supplier.code == "RTS"
        assert Item.objects.get(reference="HUILE-46").unit == "l"
        assert not Item.objects.filter(reference="X").exists()


@pytest.mark.django_db
def test_history_import_feeds_kpi_and_costs(client, admin_a, tenant_a, equipment_a):
    client.force_login(admin_a)
    rows = [
        ["Début", "Fin", "Équipement", "Type", "Intitulé", "Arrêt de production", "Durée d'arrêt (h)", "Main-d'œuvre", "Pièces"],
        ["13/01/2025 08:00", "13/01/2025 11:30", "PRS-A1", "correctif", "Fuite vérin", "oui", "4", "120", "640"],
        ["10/02/2025 09:00", "10/02/2025 10:00", "PRS-A1", "préventif", "Graissage", "non", "", "30", ""],
        ["10/02/2025 09:00", "10/02/2025 08:00", "PRS-A1", "correctif", "Fin avant début", "", "", "", ""],
    ]
    url = upload(client, "historique", rows)
    client.post(reverse("imports:confirm", args=[int(url.rstrip("/").split("/")[-1])]))
    with tenant_context(tenant_a):
        orders = WorkOrder.objects.filter(equipment=equipment_a).order_by("started_at")
        assert orders.count() == 2 and all(o.status == "validated" for o in orders)
        assert orders[0].number.startswith("OT-2025-") and orders[0].total_cost == D("760")
        stop = Downtime.objects.get(work_order=orders[0])
        assert (stop.ended_at - stop.started_at).total_seconds() == 4 * 3600 and stop.origin == "failure"
        from apps.kpi import selectors

        rel = selectors.reliability(selectors.scope(), date(2025, 1, 1), date(2025, 1, 31))
        assert rel.failures == 1 and rel.downtime_failure == D("4")
    url = upload(client, "historique", rows[:2])  # renvoyé : déjà importé
    assert client.get(url).context["skips"] == 1


@pytest.mark.django_db
def test_imports_rights_and_isolation(client, tenant_a, admin_a, admin_b):
    client.force_login(make_user(tenant_a, "technician", "tech_imp"))
    assert client.get(reverse("imports:home")).status_code == 403
    client.force_login(admin_a)
    url = upload(client, "fournisseurs", [["Code", "Raison sociale"], ["RTS", "Roulements"]])
    client.force_login(admin_b)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_work_order_sheet_export_and_equipment_sheet(client, admin_a, tenant_a, equipment_a):
    from apps.workorders import services as wo_services

    with tenant_context(tenant_a):
        wo = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title="Changer courroie", kind="corrective", priority=2)
    client.force_login(admin_a)
    pdf = client.get(reverse("workorders:wo_pdf", args=[wo.pk]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    excel = client.get(reverse("workorders:wo_export"))
    assert excel.status_code == 200
    sheet = load_workbook(io.BytesIO(excel.content)).active
    assert sheet["A2"].value == wo.number
    sheet_pdf = client.get(reverse("assets:equipment_pdf", args=[equipment_a.pk]))
    assert sheet_pdf.status_code == 200 and sheet_pdf.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_monthly_report_generation_and_scheduler(client, admin_a, tenant_a, equipment_a):
    from apps.kpi.models import MonthlyReport
    from apps.kpi.reports import generate_missing_for_all_tenants

    assert generate_missing_for_all_tenants(today=date(2026, 3, 5)) >= 1
    assert generate_missing_for_all_tenants(today=date(2026, 3, 20)) == 0  # déjà produit
    with tenant_context(tenant_a):
        report = MonthlyReport.objects.get(year=2026, month=2)
        assert report.file.name.startswith(f"tenant_{tenant_a.pk}/")
    client.force_login(admin_a)
    assert client.get(reverse("kpi:reports")).status_code == 200
    response = client.get(reverse("kpi:report_file", args=[report.pk]))
    assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF")
    client.post(reverse("kpi:report_generate"), {"mois": "2026-01"})
    client.post(reverse("kpi:report_generate"), {"mois": "2099-01"})  # mois futur refusé
    with tenant_context(tenant_a):
        assert set(MonthlyReport.objects.values_list("month", "year")) == {(2, 2026), (1, 2026)}


def test_location_lookup_is_case_insensitive():
    from apps.condition.importer import normalize

    assert normalize("Usine") == normalize("USINE") and isinstance(Location.Kind.WORKSHOP.value, str)


@pytest.mark.django_db
def test_decimals_are_rounded_to_field_precision(client, admin_a, tenant_a, equipment_a):
    client.force_login(admin_a)
    url = upload(client, "equipements", [["Code", "Désignation", "Famille", "Localisation", "Heures requises par jour"],
                                         ["CMP-20", "Compresseur", "FAM", "SITE", "15,75"]])
    client.post(reverse("imports:confirm", args=[int(url.rstrip("/").split("/")[-1])]))
    with tenant_context(tenant_a):
        assert Equipment.objects.get(code="CMP-20").required_hours_per_day == D("15.8")
