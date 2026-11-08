"""Magasin : CMP, stock négatif, réservations, délivrance aux OT, retours, inventaires, droits et isolation."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.inventory import selectors, services
from apps.inventory.models import (
    EquipmentPart,
    Item,
    StockCount,
    StockLevel,
    StockMovement,
    Warehouse,
    WorkOrderPart,
)
from apps.workforce.models import Technician
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder
from conftest import make_user

D = Decimal


@pytest.fixture
def stock_a(tenant_a, equipment_a, admin_a):
    with tenant_context(tenant_a):
        main = Warehouse.objects.create(code="MAG-C", name="Magasin central")
        line = Warehouse.objects.create(code="MAG-L", name="Magasin de ligne")
        bearing = Item.objects.create(reference="ROU-6205", designation="Roulement 6205-2RS", unit_price=D("20"), min_stock=D("4"))
        services.receive(item=bearing, warehouse=main, quantity=10, unit_cost=D("18"), user=admin_a)
        work_order = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title="Changer roulement",
                                                   kind="corrective", priority=2)
    return {"tenant": tenant_a, "main": main, "line": line, "item": bearing, "wo": work_order, "admin": admin_a,
            "equipment": equipment_a}


def reload(obj):
    return type(obj).all_tenants.get(pk=obj.pk)


# --- Valorisation et mouvements ------------------------------------------------------------------

@pytest.mark.django_db
def test_weighted_average_cost_and_movement_trail(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        services.receive(item=s["item"], warehouse=s["main"], quantity=5, unit_cost=D("24"), user=s["admin"])
        item = reload(s["item"])
        assert item.average_cost == D("20.0000")  # (10 × 18 + 5 × 24) / 15
        services.issue(item=item, warehouse=s["main"], quantity=3, user=s["admin"], reason="Casse")
        item = reload(item)
        assert item.average_cost == D("20.0000")  # une sortie ne change pas le CMP
        assert services.physical_quantity(item) == D("12")
        last = StockMovement.objects.filter(item=item).first()
        assert last.kind == "issue" and last.quantity == D("-3") and last.value == D("-60.000") and last.stock_after == D("12")
        assert last.number.startswith("MVT-")


@pytest.mark.django_db
def test_negative_stock_and_missing_reason_are_refused(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        with pytest.raises(ValidationError):
            services.issue(item=s["item"], warehouse=s["main"], quantity=11, user=s["admin"], reason="Essai")
        with pytest.raises(ValidationError):
            services.issue(item=s["item"], warehouse=s["main"], quantity=1, user=s["admin"], reason="")
        with pytest.raises(ValidationError):
            services.issue(item=s["item"], warehouse=s["line"], quantity=1, user=s["admin"], reason="Vide")
        with pytest.raises(ValidationError):
            services.receive(item=s["item"], warehouse=s["main"], quantity=0, unit_cost=1, user=s["admin"])
        assert services.physical_quantity(s["item"]) == D("10")


@pytest.mark.django_db
def test_movements_cannot_be_changed_or_deleted(stock_a):
    with tenant_context(stock_a["tenant"]):
        movement = StockMovement.objects.first()
        movement.quantity = 99
        with pytest.raises(ValidationError):
            movement.save()
        with pytest.raises(ValidationError):
            movement.delete()


@pytest.mark.django_db
def test_transfer_and_adjustment(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        services.transfer(item=s["item"], source=s["main"], destination=s["line"], quantity=4, user=s["admin"])
        assert services.physical_quantity(s["item"], s["main"]) == D("6")
        assert services.physical_quantity(s["item"], s["line"]) == D("4")
        pair = StockMovement.objects.filter(kind__in=["transfer_out", "transfer_in"])
        assert pair.count() == 2 and len({m.number for m in pair}) == 1
        with pytest.raises(ValidationError):
            services.transfer(item=s["item"], source=s["main"], destination=s["main"], quantity=1, user=s["admin"])
        services.adjust(item=s["item"], warehouse=s["line"], new_quantity=3, user=s["admin"], reason="Pièce cassée")
        assert services.physical_quantity(s["item"], s["line"]) == D("3")
        with pytest.raises(ValidationError):
            services.adjust(item=s["item"], warehouse=s["line"], new_quantity=3, user=s["admin"], reason="Rien")


# --- Réservations et OT ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_request_reserves_then_issue_and_return_cost_the_work_order(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        line = services.request_part(work_order=s["wo"], item=s["item"], quantity=8, user=s["admin"])
        assert line.warehouse == s["main"]  # le magasin le mieux approvisionné
        assert services.available_quantity(s["item"]) == D("2")
        # Le réservé ne peut pas partir hors OT.
        with pytest.raises(ValidationError):
            services.issue(item=s["item"], warehouse=s["main"], quantity=3, user=s["admin"], reason="Autre besoin")
        services.issue_request(line, quantity=5, user=s["admin"])
        line = reload(line)
        assert line.status == "partial" and line.issued == D("5") and line.issued_value == D("90.000")
        assert services.available_quantity(s["item"]) == D("2")  # 5 en stock, 3 encore réservés
        with pytest.raises(ValidationError):
            services.issue_request(line, quantity=4, user=s["admin"])  # plus que le reste demandé
        services.issue_request(line, quantity=3, user=s["admin"])
        line = reload(line)
        assert line.status == "issued"
        services.return_request(line, quantity=2, user=s["admin"])
        line = reload(line)
        assert line.returned == D("2") and line.issued_value == D("108.000")
        assert services.physical_quantity(s["item"]) == D("4")
        assert wo_services.compute_costs(s["wo"])["parts"] == D("108.000")
        movement = StockMovement.objects.filter(kind="issue").first()
        assert movement.work_order == s["wo"] and movement.equipment == s["equipment"]


@pytest.mark.django_db
def test_closing_the_work_order_releases_reservations(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        line = services.request_part(work_order=s["wo"], item=s["item"], quantity=3, user=s["admin"])
        services.issue_request(line, quantity=1, user=s["admin"])
        other = services.request_part(work_order=s["wo"], item=s["item"], quantity=2, user=s["admin"])
        wo_services.cancel(reload(s["wo"]), user=s["admin"], reason="Doublon")
        assert reload(line).status == "closed" and reload(other).status == "cancelled"
        assert services.reserved_quantity(s["item"]) == 0
        with pytest.raises(ValidationError):
            services.request_part(work_order=reload(s["wo"]), item=s["item"], quantity=1, user=s["admin"])


@pytest.mark.django_db
def test_validated_cost_includes_stock_parts(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        line = services.request_part(work_order=s["wo"], item=s["item"], quantity=2, user=s["admin"])
        services.issue_request(line, quantity=2, user=s["admin"])
        WorkOrder.objects.filter(pk=s["wo"].pk).update(status="done")
        validated = wo_services.validate(reload(s["wo"]), user=s["admin"])
        assert validated.parts_cost == D("36.000")
        with pytest.raises(ValidationError):
            services.return_request(line, quantity=1, user=s["admin"])  # coûts figés


@pytest.mark.django_db
def test_preventive_plan_parts_are_reserved_on_generation(stock_a):
    from apps.preventive.models import PlanPart, PreventivePlan
    from apps.preventive.services import generate_for_plan

    s = stock_a
    with tenant_context(s["tenant"]):
        plan = PreventivePlan.objects.create(
            code="PP-1", name="Graissage", equipment=s["equipment"], operations="Graisser", trigger_mode="calendar",
            period_value=1, period_unit="month", next_due_date=timezone.localdate(), lead_days=7,
        )
        PlanPart.objects.create(plan=plan, item=s["item"], reference=s["item"].reference, designation=s["item"].designation, quantity=2)
        PlanPart.objects.create(plan=plan, designation="Chiffon", quantity=1)
        work_order = generate_for_plan(plan)
        lines = list(work_order.stock_parts.all())
        assert len(lines) == 1 and lines[0].from_plan and lines[0].quantity == D("2")
        assert services.reserved_quantity(s["item"]) == D("2")


# --- Inventaire -----------------------------------------------------------------------------------

@pytest.mark.django_db
def test_stock_count_records_differences(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        other = Item.objects.create(reference="CRT-1", designation="Courroie")
        services.receive(item=other, warehouse=s["main"], quantity=3, unit_cost=5, user=s["admin"])
        count = services.start_count(warehouse=s["main"], user=s["admin"])
        assert count.number.startswith("INV-") and count.lines.count() == 2
        with pytest.raises(ValidationError):
            services.start_count(warehouse=s["main"], user=s["admin"])  # un seul inventaire ouvert par magasin
        lines = {line.item.reference: line for line in count.lines.select_related("item")}
        with pytest.raises(ValidationError):
            services.save_counts(count, {lines["ROU-6205"].pk: "abc"})
        services.save_counts(count, {lines["ROU-6205"].pk: "9", lines["CRT-1"].pk: ""})
        services.validate_count(count, user=s["admin"])
        count = reload(count)
        assert count.status == StockCount.Status.VALIDATED
        assert services.physical_quantity(s["item"], s["main"]) == D("9")
        assert services.physical_quantity(other, s["main"]) == D("3")  # non compté : inchangé
        assert StockMovement.objects.filter(kind="inventory", count=count).get().quantity == D("-1")


# --- Écrans, droits et isolation -------------------------------------------------------------------

@pytest.mark.django_db
def test_screens_render(client, stock_a):
    s = stock_a
    client.force_login(s["admin"])
    with tenant_context(s["tenant"]):
        services.request_part(work_order=s["wo"], item=s["item"], quantity=1, user=s["admin"])
        count = services.start_count(warehouse=s["main"], user=s["admin"])
    urls = [
        reverse("inventory:item_list"), reverse("inventory:item_list") + "?etat=sous-mini", reverse("inventory:item_create"),
        s["item"].get_absolute_url(), reverse("inventory:item_update", args=[s["item"].pk]),
        reverse("inventory:movement_list"), reverse("inventory:request_queue"), reverse("inventory:count_list"),
        count.get_absolute_url(), reverse("inventory:family_list"), reverse("inventory:warehouse_list"),
        reverse("inventory:supplier_list"), reverse("inventory:supplier_create"),
        reverse("inventory:movement_create", args=["entree"]) + f"?article={s['item'].pk}",
        reverse("inventory:movement_create", args=["sortie"]), reverse("inventory:movement_create", args=["transfert"]),
        reverse("inventory:movement_create", args=["ajustement"]),
        s["wo"].get_absolute_url(), reverse("workorders:wo_execute", args=[s["wo"].pk]),
        s["equipment"].get_absolute_url() + "?onglet=pieces", reverse("dashboard:home"),
        reverse("core:search") + "?q=ROU",
    ]
    for url in urls:
        assert client.get(url).status_code == 200, url
    for url in (reverse("inventory:item_export"), reverse("inventory:movement_export"), reverse("inventory:count_export", args=[count.pk])):
        response = client.get(url)
        assert response.status_code == 200 and response["Content-Type"].startswith("application/vnd.openxml"), url


@pytest.mark.django_db
def test_movement_and_item_forms(client, stock_a):
    s = stock_a
    client.force_login(s["admin"])
    response = client.post(reverse("inventory:movement_create", args=["entree"]), {
        "item": "rou-6205", "warehouse": s["main"].pk, "quantity": "2", "unit_cost": "21", "document": "BL 42", "reason": "Réception",
    })
    assert response.status_code == 302
    response = client.post(reverse("inventory:movement_create", args=["sortie"]), {
        "item": "ROU-6205", "warehouse": s["main"].pk, "quantity": "50", "reason": "Trop",
    })
    assert response.status_code == 200 and "disponible" in response.content.decode()
    response = client.post(reverse("inventory:item_create"), {
        "reference": " crt-spz ", "designation": "Courroie SPZ", "unit": "u", "unit_price": "14", "min_stock": "2", "max_stock": "1",
    })
    assert response.status_code == 200  # maxi < mini refusé
    response = client.post(reverse("inventory:item_create"), {
        "reference": " crt-spz ", "designation": "Courroie SPZ", "unit": "u", "unit_price": "14", "min_stock": "2", "max_stock": "6",
    })
    assert response.status_code == 302
    with tenant_context(s["tenant"]):
        assert Item.objects.filter(reference="CRT-SPZ").exists()
        assert services.physical_quantity(s["item"]) == D("12")
    duplicate = client.post(reverse("inventory:item_create"), {"reference": "CRT-SPZ", "designation": "X", "unit": "u", "unit_price": "1", "min_stock": "0"})
    assert duplicate.status_code == 200


@pytest.mark.django_db
def test_technician_requests_storekeeper_issues(client, stock_a, tenant_a):
    s = stock_a
    tech_user = make_user(tenant_a, "technician", "tech_stock")
    keeper = make_user(tenant_a, "storekeeper", "magasin")
    with tenant_context(tenant_a):
        technician = Technician.objects.create(employee_number="T9", first_name="Ali", last_name="B", hourly_rate=10, user=tech_user)
        s["wo"].technicians.add(technician)
    client.force_login(tech_user)
    url = reverse("inventory:wo_request_part", args=[s["wo"].pk])
    client.post(url, {"item": "ROU-6205", "quantity": "2"})
    with tenant_context(tenant_a):
        line = WorkOrderPart.objects.get()
    assert client.post(reverse("inventory:request_issue", args=[line.pk]), {"quantity": "2"}).status_code == 403
    assert client.get(reverse("inventory:movement_create", args=["entree"])).status_code == 403
    client.force_login(keeper)
    client.post(reverse("inventory:request_issue", args=[line.pk]), {"quantity": "2"})
    with tenant_context(tenant_a):
        assert reload(line).status == "issued" and services.physical_quantity(s["item"]) == D("8")
    # Le magasinier n'a pas accès aux OT : il voit la file et fait le retour depuis le magasin.
    queue = client.get(reverse("inventory:request_queue"))
    assert queue.status_code == 200 and s["wo"].number in queue.content.decode()
    assert s["wo"].get_absolute_url() not in queue.content.decode()
    client.post(reverse("inventory:request_return", args=[line.pk]), {"quantity": "1"})
    with tenant_context(tenant_a):
        assert reload(line).returned == D("1") and services.physical_quantity(s["item"]) == D("9")
    # Un technicien non affecté à l'OT ne peut pas demander de pièce.
    other = make_user(tenant_a, "technician", "tech_autre")
    client.force_login(other)
    client.post(url, {"item": "ROU-6205", "quantity": "1"})
    with tenant_context(tenant_a):
        assert WorkOrderPart.objects.count() == 1


@pytest.mark.django_db
def test_equipment_bill_of_materials(client, stock_a):
    s = stock_a
    client.force_login(s["admin"])
    client.post(reverse("inventory:equipment_part_add", args=[s["equipment"].pk]), {"item": "ROU-6205", "quantity": "2", "position": "Palier"})
    client.post(reverse("inventory:equipment_part_add", args=[s["equipment"].pk]), {"item": "ROU-6205", "quantity": "1"})
    with tenant_context(s["tenant"]):
        link = EquipmentPart.objects.get()
        assert link.quantity == D("2") and link.position == "Palier"
    page = client.get(s["equipment"].get_absolute_url() + "?onglet=pieces").content.decode()
    assert "ROU-6205" in page


@pytest.mark.django_db
def test_isolation_between_companies(client, stock_a, admin_b, tenant_b):
    s = stock_a
    client.force_login(admin_b)
    assert client.get(s["item"].get_absolute_url()).status_code == 404
    response = client.post(reverse("inventory:movement_create", args=["sortie"]), {
        "item": "ROU-6205", "warehouse": s["main"].pk, "quantity": "1", "reason": "Vol",
    })
    assert response.status_code == 200 and response.context["form"].errors
    with tenant_context(s["tenant"]):
        line = services.request_part(work_order=s["wo"], item=s["item"], quantity=1, user=s["admin"])
    assert client.post(reverse("inventory:request_issue", args=[line.pk]), {"quantity": "1"}).status_code == 404
    with tenant_context(tenant_b):
        assert Item.objects.count() == 0 and StockLevel.objects.count() == 0
        assert selectors.search_items("ROU", 5) == []


@pytest.mark.django_db
def test_below_minimum_and_search(stock_a):
    s = stock_a
    with tenant_context(s["tenant"]):
        services.request_part(work_order=s["wo"], item=s["item"], quantity=7, user=s["admin"])
        below = list(selectors.below_minimum())
        assert [item.reference for item in below] == ["ROU-6205"] and below[0].available == D("3")
        results = selectors.search_items("6205", 5)
        assert results and results[0].badge


@pytest.mark.django_db
def test_movement_dates_follow_given_moment(stock_a):
    s = stock_a
    past = timezone.now() - timedelta(days=10)
    with tenant_context(s["tenant"]):
        movement = services.receive(item=s["item"], warehouse=s["main"], quantity=1, unit_cost=18, user=s["admin"], moved_at=past)
        assert movement.moved_at == past


@pytest.mark.django_db
def test_signed_slips_for_issue_and_return(client, stock_a):
    s = stock_a
    client.force_login(s["admin"])
    with tenant_context(s["tenant"]):
        first = services.request_part(work_order=s["wo"], item=s["item"], quantity=2, user=s["admin"])
        other = Item.objects.create(reference="CRT-1", designation="Courroie SPZ")
        services.receive(item=other, warehouse=s["main"], quantity=3, unit_cost=5, user=s["admin"])
        second = services.request_part(work_order=s["wo"], item=other, quantity=1, user=s["admin"])
    response = client.post(reverse("inventory:request_issue", args=[first.pk]), {"quantity": "2"}, follow=True)
    page = response.content.decode()
    assert "bon de sortie" in page.lower()
    client.post(reverse("inventory:request_issue", args=[second.pk]), {"quantity": "1"})
    with tenant_context(s["tenant"]):
        issue = StockMovement.objects.filter(kind="issue", request_line=first).get()
    slip = client.get(reverse("inventory:movement_slip", args=[issue.pk])).content.decode()
    # Les deux délivrances du jour pour le même OT figurent sur le même bon, avec les deux signatures.
    assert "ROU-6205" in slip and "CRT-1" in slip and s["wo"].number in slip
    assert "Reçu par (technicien)" in slip and "Remis par (magasin)" in slip
    client.post(reverse("inventory:request_return", args=[first.pk]), {"quantity": "1"})
    with tenant_context(s["tenant"]):
        back = StockMovement.objects.get(kind="return")
        receipt = StockMovement.objects.filter(kind="receipt").first()
    slip = client.get(reverse("inventory:movement_slip", args=[back.pk])).content.decode()
    slip = slip[slip.index('id="contenu"'):]  # le bon lui-même, sans la barre supérieure (cloche des notifications)
    assert "Bon de retour" in slip and "Rapporté par (technicien)" in slip and "CRT-1" not in slip
    assert client.get(reverse("inventory:movement_slip", args=[receipt.pk])).status_code == 404


# --- Phase 5B : demandes d'achat imprimables, entrée sur bon de commande, historique des prix --------

@pytest.mark.django_db
def test_order_receipt_updates_stock_cost_and_supplier_price(client, stock_a):
    from apps.inventory.models import ItemSupplier, Supplier

    s = stock_a
    with tenant_context(s["tenant"]):
        supplier = Supplier.objects.create(code="RTS", name="Roulements du Sahel")
        belt = Item.objects.create(reference="CRT-SPZ", designation="Courroie SPZ")
    client.force_login(s["admin"])
    url = reverse("inventory:order_receipt")
    assert client.get(url).status_code == 200
    data = {"supplier": supplier.pk, "purchase_order": "ACH-2026-117", "delivery_note": "BL 5521", "warehouse": s["main"].pk,
            "rows": "8", "l-0-item": "ROU-6205", "l-0-quantity": "10", "l-0-unit_cost": "22",
            "l-1-item": "crt-spz", "l-1-quantity": "4", "l-1-unit_cost": "13,5"}
    # Une ligne fausse : rien n'est enregistré.
    bad = client.post(url, {**data, "l-2-item": "INCONNU", "l-2-quantity": "1", "l-2-unit_cost": "1"})
    assert bad.status_code == 200 and "Ligne 3" in bad.content.decode()
    with tenant_context(s["tenant"]):
        assert StockMovement.objects.filter(purchase_order="ACH-2026-117").count() == 0
    assert client.post(url, data).status_code == 302
    with tenant_context(s["tenant"]):
        moves = StockMovement.objects.filter(purchase_order="ACH-2026-117")
        assert moves.count() == 2 and len({m.number for m in moves}) == 1
        assert reload(s["item"]).average_cost == D("20.0000")  # (10 × 18 + 10 × 22) / 20
        assert ItemSupplier.objects.get(item=s["item"], supplier=supplier).price == D("22.000")
        link = ItemSupplier.objects.get(item=belt, supplier=supplier)
        assert link.price == D("13.500") and link.is_preferred
        assert [m.unit_cost for m in services.price_history(s["item"])] == [D("22.0000"), D("18.0000")]
    page = client.get(s["item"].get_absolute_url()).content.decode()
    assert "ACH-2026-117" in page and "price-series" in page


@pytest.mark.django_db
def test_purchase_request_create_print_edit_delete(client, stock_a):
    s = stock_a
    client.force_login(s["admin"])
    url = reverse("inventory:purchase_create")
    assert client.get(url + f"?work_order={s['wo'].pk}").status_code == 200
    empty = client.post(url, {"requested_on": "2026-11-07", "rows": "6"})
    assert empty.status_code == 200 and "au moins une ligne" in empty.content.decode()
    response = client.post(url, {
        "requested_on": "2026-11-07", "reason": "Réparation", "work_order": s["wo"].pk, "rows": "6",
        "l-0-item": "ROU-6205", "l-0-quantity": "4",
        "l-1-designation": "Capteur de pression 0-250 bar", "l-1-quantity": "1", "l-1-unit": "pièce", "l-1-estimated_price": "480",
        "l-2-designation": "Sans quantité",
    })
    assert response.status_code == 200 and "Ligne 3" in response.content.decode()
    response = client.post(url, {
        "requested_on": "2026-11-07", "reason": "Réparation", "work_order": s["wo"].pk, "rows": "6",
        "l-0-item": "ROU-6205", "l-0-quantity": "4",
        "l-1-designation": "Capteur de pression 0-250 bar", "l-1-quantity": "1", "l-1-unit": "pièce", "l-1-estimated_price": "480",
    })
    from apps.inventory.models import PurchaseRequest

    with tenant_context(s["tenant"]):
        purchase = PurchaseRequest.objects.get()
        lines = list(purchase.lines.all())
    assert response.status_code == 302 and purchase.number.startswith("DA-")
    assert lines[0].designation == "Roulement 6205-2RS" and lines[0].estimated_price == D("20.000") and lines[0].unit == "pièce"
    assert lines[1].item is None
    printed = client.get(purchase.get_absolute_url() + "?imprimer=1").content.decode()
    assert "Visa du responsable maintenance" in printed and "Reçu par le service achats" in printed and "560,000" in printed.replace(" ", "").replace(" ", "")
    client.post(reverse("inventory:purchase_update", args=[purchase.pk]), {
        "requested_on": "2026-11-07", "rows": "8", "l-0-item": "ROU-6205", "l-0-quantity": "6",
    })
    with tenant_context(s["tenant"]):
        assert [line.quantity for line in reload(purchase).lines.all()] == [D("6")]
    client.post(reverse("inventory:purchase_delete", args=[purchase.pk]))
    with tenant_context(s["tenant"]):
        assert not PurchaseRequest.objects.exists()


@pytest.mark.django_db
def test_reorder_prepares_one_request_per_preferred_supplier(client, stock_a):
    from apps.inventory.models import ItemSupplier, PurchaseRequest, Supplier

    s = stock_a
    with tenant_context(s["tenant"]):
        Item.objects.filter(pk=s["item"].pk).update(min_stock=D("12"), max_stock=D("20"))
        filt = Item.objects.create(reference="FLT-1", designation="Filtre", min_stock=D("2"), unit_price=D("50"))
        supplier = Supplier.objects.create(code="HTD", name="Hydro-Tech")
        ItemSupplier.objects.create(item=s["item"], supplier=supplier, price=D("19"), is_preferred=True)
        assert services.reorder_quantity(reload(s["item"]), D("10")) == D("10")
        assert services.reorder_quantity(filt, D("0")) == D("2")
    client.force_login(s["admin"])
    page = client.get(reverse("inventory:purchase_reorder")).content.decode()
    assert "ROU-6205" in page and "FLT-1" in page
    client.post(reverse("inventory:purchase_reorder"), {"item": [s["item"].pk, filt.pk]})
    with tenant_context(s["tenant"]):
        requests = {r.supplier_id: r for r in PurchaseRequest.objects.all()}
        assert set(requests) == {supplier.pk, None}
        line = requests[supplier.pk].lines.get()
        assert line.quantity == D("10") and line.estimated_price == D("19.000")
        assert requests[None].lines.get().quantity == D("2")


@pytest.mark.django_db
def test_purchase_rights(client, stock_a, tenant_a, admin_b):
    viewer = make_user(tenant_a, "production_manager", "prod")
    client.force_login(viewer)
    assert client.get(reverse("inventory:purchase_create")).status_code == 403
    assert client.get(reverse("inventory:order_receipt")).status_code == 403
    keeper = make_user(tenant_a, "storekeeper", "mag2")
    client.force_login(keeper)
    assert client.get(reverse("inventory:purchase_create")).status_code == 200
    assert client.get(reverse("inventory:order_receipt")).status_code == 200
