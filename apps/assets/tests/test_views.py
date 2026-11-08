import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.assets.models import Equipment, EquipmentFamily, Location, Meter
from apps.core.models import Attachment, AuditLog
from apps.core.tenancy import tenant_context


@pytest.mark.django_db
def test_list_shows_only_own_equipment(client, admin_a, equipment_a, equipment_b):
    client.force_login(admin_a)
    response = client.get(reverse("assets:equipment_list"))
    assert response.status_code == 200
    codes = [item.code for item in response.context["equipment_list"]]
    assert codes == ["PRS-A1"]


@pytest.mark.django_db
def test_list_filters_and_htmx_partial(client, admin_a, tenant_a, equipment_a):
    from conftest import make_equipment

    make_equipment(tenant_a, "CMP-01", status=Equipment.Status.BROKEN)
    client.force_login(admin_a)
    response = client.get(reverse("assets:equipment_list"), {"statut": "broken"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="equipment-results")
    assert [t.name for t in response.templates][0] == "assets/_equipment_results.html"
    assert [item.code for item in response.context["equipment_list"]] == ["CMP-01"]
    response = client.get(reverse("assets:equipment_list"), {"q": "prs"})
    assert [item.code for item in response.context["equipment_list"]] == ["PRS-A1"]


@pytest.mark.django_db
def test_detail_of_another_tenant_is_not_found(client, admin_a, equipment_b):
    client.force_login(admin_a)
    assert client.get(reverse("assets:equipment_detail", args=[equipment_b.pk])).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["resume", "compteurs", "documents", "historique"])
def test_detail_tabs_render(client, admin_a, equipment_a, tab):
    client.force_login(admin_a)
    response = client.get(reverse("assets:equipment_detail", args=[equipment_a.pk]), {"onglet": tab})
    assert response.status_code == 200
    assert response.context["tab"] == tab


@pytest.mark.django_db
def test_create_equipment_and_audit(client, admin_a, tenant_a):
    with tenant_context(tenant_a):
        location = Location.objects.create(code="S", name="Usine", kind="site")
        family = EquipmentFamily.objects.create(code="F", name="Compresseurs")
    client.force_login(admin_a)
    response = client.post(reverse("assets:equipment_create"), {
        "code": "cmp-09", "designation": "Compresseur", "family": family.pk, "location": location.pk,
        "status": "in_service", "criticality": "A", "required_hours_per_day": "24",
    })
    assert response.status_code == 302, response.context["form"].errors if response.context else ""
    with tenant_context(tenant_a):
        equipment = Equipment.objects.get(code="CMP-09")
    assert equipment.created_by == admin_a
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(equipment.pk)).exists()


@pytest.mark.django_db
def test_form_refuses_location_from_another_tenant(client, admin_a, tenant_a, tenant_b):
    with tenant_context(tenant_a):
        family = EquipmentFamily.objects.create(code="F", name="Presses")
    with tenant_context(tenant_b):
        foreign_location = Location.objects.create(code="S", name="Usine B", kind="site")
    client.force_login(admin_a)
    response = client.post(reverse("assets:equipment_create"), {
        "code": "X1", "designation": "X", "family": family.pk, "location": foreign_location.pk,
        "status": "in_service", "criticality": "B", "required_hours_per_day": "16",
    })
    assert response.status_code == 200
    assert "location" in response.context["form"].errors


@pytest.mark.django_db
def test_update_records_changes_in_history(client, admin_a, equipment_a):
    client.force_login(admin_a)
    response = client.post(reverse("assets:equipment_update", args=[equipment_a.pk]), {
        "code": equipment_a.code, "designation": "Nouvelle désignation", "family": equipment_a.family_id,
        "location": equipment_a.location_id, "status": "in_service", "criticality": "A", "required_hours_per_day": "16",
    })
    assert response.status_code == 302
    entry = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(equipment_a.pk)).latest("at")
    assert "Désignation" in entry.changes or "désignation" in entry.changes


@pytest.mark.django_db
def test_technician_can_view_but_not_create(client, technician_a, equipment_a):
    client.force_login(technician_a)
    assert client.get(reverse("assets:equipment_list")).status_code == 200
    assert client.get(reverse("assets:equipment_create")).status_code == 403
    response = client.post(reverse("assets:equipment_change_status", args=[equipment_a.pk]), {"status": "broken"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_status_change_is_logged(client, admin_a, equipment_a, tenant_a):
    client.force_login(admin_a)
    client.post(reverse("assets:equipment_change_status", args=[equipment_a.pk]), {"status": "broken"})
    equipment_a.refresh_from_db()
    assert equipment_a.status == "broken"
    assert AuditLog.objects.filter(object_id=str(equipment_a.pk), action=AuditLog.Action.UPDATE).exists()


@pytest.mark.django_db
def test_technician_can_record_a_reading(client, technician_a, equipment_a, tenant_a):
    with tenant_context(tenant_a):
        meter = Meter.objects.create(equipment=equipment_a, name="Heures", kind="hours")
    client.force_login(technician_a)
    response = client.post(reverse("assets:reading_create", args=[meter.pk]), {"value": "150", "reading_at": "2026-01-10T08:00"})
    assert response.status_code == 302
    meter.refresh_from_db()
    assert meter.current_value == 150


@pytest.mark.django_db
def test_attachment_upload_download_and_isolation(client, admin_a, admin_b, equipment_a):
    client.force_login(admin_a)
    upload = SimpleUploadedFile("manuel.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    response = client.post(reverse("assets:attachment_upload", args=[equipment_a.pk]), {"file": upload, "category": "technical", "title": ""})
    assert response.status_code == 302
    attachment = Attachment.all_tenants.get()
    assert client.get(reverse("assets:attachment_download", args=[attachment.pk])).status_code == 200
    client.force_login(admin_b)
    assert client.get(reverse("assets:attachment_download", args=[attachment.pk])).status_code == 404


@pytest.mark.django_db
def test_disallowed_attachment_type_is_rejected(client, admin_a, equipment_a):
    client.force_login(admin_a)
    upload = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")
    client.post(reverse("assets:attachment_upload", args=[equipment_a.pk]), {"file": upload, "category": "other"})
    assert Attachment.all_tenants.count() == 0


@pytest.mark.django_db
def test_global_search_finds_own_equipment_only(client, admin_a, equipment_a, equipment_b):
    client.force_login(admin_a)
    response = client.get(reverse("core:search"), {"q": "PRS"})
    titles = [result.title for result in response.context["results"]]
    assert any("PRS-A1" in title for title in titles)
    assert not any("PRS-B1" in title for title in titles)


@pytest.mark.django_db
def test_qr_code_and_resolution(client, admin_a, admin_b, equipment_a):
    client.force_login(admin_a)
    svg = client.get(reverse("assets:equipment_qr", args=[equipment_a.pk]))
    assert svg.status_code == 200 and svg["Content-Type"] == "image/svg+xml"
    resolve = client.get(reverse("assets:qr_resolve", args=[equipment_a.qr_token]))
    assert resolve.status_code == 302 and resolve["Location"] == equipment_a.get_absolute_url()
    client.force_login(admin_b)
    assert client.get(reverse("assets:qr_resolve", args=[equipment_a.qr_token])).status_code == 404


@pytest.mark.django_db
def test_excel_export(client, admin_a, equipment_a):
    client.force_login(admin_a)
    response = client.get(reverse("assets:equipment_export"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert AuditLog.objects.filter(action=AuditLog.Action.EXPORT).exists()


@pytest.mark.django_db
def test_location_tree_and_referentials_pages(client, admin_a, equipment_a):
    client.force_login(admin_a)
    assert client.get(reverse("assets:location_tree")).status_code == 200
    assert client.get(reverse("assets:family_list")).status_code == 200
    assert client.get(reverse("assets:location_create")).status_code == 200


@pytest.mark.django_db
def test_api_is_isolated_and_respects_capabilities(client, admin_a, technician_a, equipment_a, equipment_b, tenant_a):
    client.force_login(admin_a)
    response = client.get("/api/v1/equipements/")
    assert response.status_code == 200
    assert [item["code"] for item in response.json()["results"]] == ["PRS-A1"]
    assert client.get(f"/api/v1/equipements/{equipment_b.pk}/").status_code == 404

    client.force_login(technician_a)
    response = client.post("/api/v1/localisations/", {"code": "X", "name": "X", "kind": "site"}, content_type="application/json")
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_renders_with_real_data(client, admin_a, equipment_a):
    client.force_login(admin_a)
    response = client.get(reverse("dashboard:home"))
    assert response.status_code == 200
    assert response.context["summary"]["total"] == 1


@pytest.mark.django_db
def test_load_demo_command_is_idempotent():
    from django.core.management import call_command

    from apps.core.models import Tenant
    from apps.preventive.models import PreventivePlan
    from apps.workorders.models import WorkOrder

    call_command("load_demo", password="Demo-EasyMaint-2026!")
    tenant = Tenant.objects.get(code="demo")
    with tenant_context(tenant):
        first_count = WorkOrder.objects.count()
    call_command("load_demo", password="Demo-EasyMaint-2026!")
    with tenant_context(tenant):
        assert Equipment.objects.count() == 21
        assert Equipment.objects.filter(status="broken").count() == 2
        assert Meter.objects.filter(readings__isnull=False).distinct().count() == Meter.objects.count()
        from apps.workorders.models import Downtime

        assert WorkOrder.objects.count() == first_count >= 16  # pas de doublon au 2e lancement
        assert PreventivePlan.objects.count() == 9
        # La génération automatique a produit le contrôle hebdomadaire de la presse PRS-INJ-03.
        assert WorkOrder.objects.filter(preventive_plan__code="PP-INJ03-SEC").exclude(status="validated").count() == 1
        # Chaque plan a au plus un OT en attente.
        for plan in PreventivePlan.objects.all():
            assert plan.work_orders.exclude(status__in=["validated", "cancelled"]).count() <= 1
        # Conditionnel : 4 alertes actives, dont la vibration du CMP-02 qui a donné une demande d'intervention.
        from apps.condition.models import Alert, ImportProfile, MeasurementSession

        assert MeasurementSession.objects.count() == 35
        assert ImportProfile.objects.count() == 1
        active = Alert.objects.exclude(status="closed")
        assert active.count() == 4
        vibration = active.get(point__equipment__code="CMP-02", parameter__code="VIB-V")
        assert vibration.level == "alarm" and vibration.work_request is not None
        # Magasin : 27 articles, stock jamais négatif, pièces demandées et délivrées sur la presse en panne.
        from apps.inventory import selectors as stock_selectors
        from apps.inventory.models import Item, StockLevel, WorkOrderPart

        assert Item.objects.count() == 27
        assert not StockLevel.objects.filter(quantity__lt=0).exists()
        below = {item.reference for item in stock_selectors.below_minimum()}
        assert {"AC-2901", "HYD-KJ-VF350"} <= below
        press_parts = WorkOrderPart.objects.filter(work_order__equipment__code="PRS-INJ-03", from_plan=False)
        assert {p.status for p in press_parts} == {"issued", "partial"}
        assert WorkOrderPart.objects.filter(from_plan=True).exists()
        from apps.inventory.models import PurchaseRequest

        assert PurchaseRequest.objects.count() >= 2
        assert PurchaseRequest.objects.filter(lines__item__reference="AC-2901").exists()
        from apps.finance.models import Budget

        assert Budget.objects.count() >= 1
        # Les équipements en panne ont bien un arrêt ouvert, et eux seuls.
        broken = set(Equipment.objects.filter(status="broken").values_list("pk", flat=True))
        assert set(Downtime.objects.filter(ended_at__isnull=True).values_list("equipment_id", flat=True)) == broken


@pytest.mark.django_db
def test_duplicate_code_gives_a_form_error_not_a_crash(client, admin_a, equipment_a):
    client.force_login(admin_a)
    response = client.post(reverse("assets:equipment_create"), {
        "code": "prs-a1", "designation": "Doublon", "family": equipment_a.family_id, "location": equipment_a.location_id,
        "status": "in_service", "criticality": "B", "required_hours_per_day": "16",
    })
    assert response.status_code == 200
    assert "code" in response.context["form"].errors
