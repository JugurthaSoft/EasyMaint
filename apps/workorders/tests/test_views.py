import pytest
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.workforce.models import Technician
from apps.workorders import services
from apps.workorders.models import ChecklistItem, PartUsage, WorkOrder, WorkRequest
from conftest import make_equipment, make_user


@pytest.fixture
def tech_user(tenant_a):
    user = make_user(tenant_a, "technician", "karim")
    with tenant_context(tenant_a):
        Technician.objects.create(employee_number="T1", first_name="Karim", last_name="Trabelsi", hourly_rate=10, user=user)
    user.refresh_from_db()
    return user


@pytest.fixture
def order_a(tenant_a, admin_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        return services.create_work_order(
            user=admin_a, equipment=equipment_a, title="Fuite vérin", kind="corrective", priority=2,
            technicians=[tech_user.technician],
        )


@pytest.fixture
def order_b(tenant_b, admin_b):
    equipment = make_equipment(tenant_b, "B-EQ")
    with tenant_context(tenant_b):
        return services.create_work_order(user=admin_b, equipment=equipment, title="Autre entreprise", kind="corrective", priority=3)


@pytest.mark.django_db
def test_lists_are_isolated(client, admin_a, order_a, order_b):
    client.force_login(admin_a)
    response = client.get(reverse("workorders:wo_list"))
    assert response.status_code == 200
    assert [wo.number for wo in response.context["work_orders"]] == [order_a.number]
    assert client.get(reverse("workorders:wo_detail", args=[order_b.pk])).status_code == 404


@pytest.mark.django_db
def test_list_filters_and_htmx(client, admin_a, order_a):
    client.force_login(admin_a)
    response = client.get(reverse("workorders:wo_list"), {"statut": "affectes", "q": "vérin"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="wo-results")
    assert [t.name for t in response.templates][0] == "workorders/_wo_results.html"
    assert len(response.context["work_orders"]) == 1
    response = client.get(reverse("workorders:wo_list"), {"statut": "termines"})
    assert len(response.context["work_orders"]) == 0


@pytest.mark.django_db
def test_technician_executes_from_the_mobile_screen(client, tech_user, order_a, tenant_a):
    with tenant_context(tenant_a):
        item = ChecklistItem.objects.create(work_order=order_a, label="Consigner", position=1)
    client.force_login(tech_user)
    assert client.get(reverse("workorders:my_work_orders")).status_code == 200
    page = reverse("workorders:wo_execute", args=[order_a.pk])
    assert client.get(page).status_code == 200

    response = client.post(reverse("workorders:wo_action", args=[order_a.pk, "start_timer"]), {"next": page})
    assert response.status_code == 302 and response["Location"] == page
    order_a.refresh_from_db()
    assert order_a.status == WorkOrder.Status.IN_PROGRESS

    client.post(reverse("workorders:wo_checklist_toggle", args=[order_a.pk, item.pk]), {"next": page})
    item.refresh_from_db()
    assert item.is_done
    client.post(reverse("workorders:wo_part_add", args=[order_a.pk]), {"designation": "Joint", "quantity": "1", "unit_cost": "0", "next": page})
    # Hors requête, aucune entreprise n'est « courante » : on compte avec le manager non filtré.
    assert PartUsage.all_tenants.filter(work_order=order_a).count() == 1
    assert client.get(page).status_code == 200


@pytest.mark.django_db
def test_external_redirect_is_ignored(client, tech_user, order_a):
    client.force_login(tech_user)
    response = client.post(reverse("workorders:wo_action", args=[order_a.pk, "start_timer"]), {"next": "https://exemple.com/"})
    assert response["Location"] == order_a.get_absolute_url()


@pytest.mark.django_db
def test_technician_cannot_validate_or_plan(client, tech_user, order_a):
    client.force_login(tech_user)
    assert client.get(reverse("workorders:wo_plan", args=[order_a.pk])).status_code == 403
    assert client.post(reverse("workorders:wo_action", args=[order_a.pk, "cancel"]), {"reason": "x"}).status_code == 403


@pytest.mark.django_db
def test_business_errors_are_messages_not_crashes(client, admin_a, order_a):
    client.force_login(admin_a)
    response = client.post(reverse("workorders:wo_action", args=[order_a.pk, "validate"]), follow=True)
    assert response.status_code == 200
    assert any("impossible" in str(m) for m in response.context["messages"])


@pytest.mark.django_db
def test_production_manager_declares_and_sees_only_own_requests(client, tenant_a, admin_a, equipment_a):
    production = make_user(tenant_a, "production_manager", "prod")
    client.force_login(production)
    response = client.post(reverse("workorders:request_create"), {
        "equipment": equipment_a.pk, "description": "Bruit anormal", "priority": "2", "production_stopped": "on",
    })
    assert response.status_code == 302
    request_obj = WorkRequest.all_tenants.get()
    with tenant_context(tenant_a):
        services.create_request(user=admin_a, equipment=equipment_a, description="Autre", priority=3, production_stopped=False)
    response = client.get(reverse("workorders:request_list"))
    assert [r.pk for r in response.context["requests_list"]] == [request_obj.pk]
    assert client.post(reverse("workorders:request_decide", args=[request_obj.pk, "accepter"])).status_code == 403


@pytest.mark.django_db
def test_manager_accepts_request_and_is_sent_to_planning(client, tenant_a, admin_a, equipment_a):
    with tenant_context(tenant_a):
        request_obj = services.create_request(user=admin_a, equipment=equipment_a, description="Fuite", priority=2, production_stopped=False)
    client.force_login(admin_a)
    response = client.post(reverse("workorders:request_decide", args=[request_obj.pk, "accepter"]), {"kind": "corrective", "priority": "1"})
    work_order = WorkOrder.all_tenants.get()
    assert response["Location"] == reverse("workorders:wo_plan", args=[work_order.pk])
    assert work_order.priority == 1


@pytest.mark.django_db
def test_planning_assigns_the_order(client, tenant_a, admin_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(user=admin_a, equipment=equipment_a, title="À planifier", kind="corrective", priority=3)
    assert work_order.status == WorkOrder.Status.TO_PLAN
    client.force_login(admin_a)
    response = client.post(reverse("workorders:wo_plan", args=[work_order.pk]), {
        "title": "À planifier", "kind": "corrective", "priority": "3", "technicians": [tech_user.technician.pk],
        "planned_date": "2026-11-10", "due_date": "2026-11-12", "estimated_hours": "2",
    })
    assert response.status_code == 302
    work_order.refresh_from_db()
    assert work_order.status == WorkOrder.Status.ASSIGNED


@pytest.mark.django_db
def test_detail_pages_render_for_each_role(client, tenant_a, admin_a, tech_user, order_a):
    for user in (admin_a, tech_user):
        client.force_login(user)
        assert client.get(order_a.get_absolute_url()).status_code == 200
    client.force_login(admin_a)
    assert client.get(reverse("workorders:wo_create")).status_code == 200
    assert client.get(reverse("workorders:failure_codes")).status_code == 200
    assert client.get(reverse("workorders:request_create")).status_code == 200


@pytest.mark.django_db
def test_search_dashboard_and_equipment_tab(client, admin_a, order_a, equipment_a):
    client.force_login(admin_a)
    response = client.get(reverse("core:search"), {"q": order_a.number})
    assert any(order_a.number in r.title for r in response.context["results"])
    response = client.get(reverse("dashboard:home"))
    assert response.context["wo"]["open"] == 1
    response = client.get(reverse("assets:equipment_detail", args=[equipment_a.pk]), {"onglet": "interventions"})
    assert response.status_code == 200
    assert list(response.context["interventions"]["orders"]) == [order_a]


@pytest.mark.django_db
def test_workforce_pages(client, admin_a, tenant_a):
    client.force_login(admin_a)
    assert client.get(reverse("workforce:technician_list")).status_code == 200
    assert client.get(reverse("workforce:referentials")).status_code == 200
    response = client.post(reverse("workforce:technician_create"), {
        "employee_number": "m-001", "first_name": "Nour", "last_name": "Chaabane", "hourly_rate": "11.5", "overtime_rate": "0", "is_active": "on",
    })
    assert response.status_code == 302
    response = client.post(reverse("workforce:technician_create"), {
        "employee_number": "M-001", "first_name": "X", "last_name": "Y", "hourly_rate": "0", "overtime_rate": "0",
    })
    assert response.status_code == 200 and "employee_number" in response.context["form"].errors
