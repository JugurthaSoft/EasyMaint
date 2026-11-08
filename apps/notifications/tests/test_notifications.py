"""Notifications dans l'application : déclencheurs, destinataires, lecture, isolation, nettoyage."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.condition.tests.test_condition import record, setup_a  # noqa: F401 (fixture)
from apps.core.tenancy import tenant_context
from apps.notifications.models import Notification
from apps.notifications.services import purge
from apps.workforce.models import Technician
from apps.workorders import services as wo_services
from conftest import make_user

K = Notification.Kind


def notes(user, kind=None):
    queryset = Notification.all_tenants.filter(user=user)
    return queryset.filter(kind=kind) if kind else queryset


@pytest.mark.django_db
def test_request_assignment_and_validation_notify_the_right_people(tenant_a, admin_a, equipment_a):
    manager = make_user(tenant_a, "maintenance_manager", "resp")
    tech_user = make_user(tenant_a, "technician", "karim")
    keeper = make_user(tenant_a, "storekeeper", "magasin")
    with tenant_context(tenant_a):
        technician = Technician.objects.create(employee_number="T1", first_name="Karim", last_name="B", hourly_rate=Decimal("10"), user=tech_user)
        wo_services.create_request(user=tech_user, equipment=equipment_a, description="Fuite vérin", priority=2, production_stopped=False)
        work_order = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title="Changer joint", kind="corrective", priority=2)
        work_order.technicians.add(technician)
        work_order.status = "done"
        work_order.save()
        work_order.save()  # un second enregistrement ne renotifie pas
    assert notes(manager, K.REQUEST).count() == 1 and notes(admin_a, K.REQUEST).count() == 1
    assert not notes(keeper, K.REQUEST).exists() and not notes(tech_user, K.REQUEST).exists()
    assigned = notes(tech_user, K.ASSIGNED).get()
    assert work_order.number in assigned.title and assigned.url == work_order.get_absolute_url()
    assert notes(manager, K.TO_VALIDATE).count() == 1 and not notes(tech_user, K.TO_VALIDATE).exists()


@pytest.mark.django_db
def test_part_request_and_alert_notifications(client, tenant_a, admin_a, equipment_a, setup_a):  # noqa: F811
    from apps.inventory import services as stock
    from apps.inventory.models import Item, Warehouse

    keeper = make_user(tenant_a, "storekeeper", "magasin")
    with tenant_context(tenant_a):
        warehouse = Warehouse.objects.create(code="MAG-C", name="Central")
        item = Item.objects.create(reference="ROU-6205", designation="Roulement", unit_price=Decimal("20"))
        stock.receive(item=item, warehouse=warehouse, quantity=5, unit_cost=Decimal("18"), user=admin_a)
        work_order = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title="Roulement", kind="corrective", priority=2)
    # L'action vient de l'administrateur connecté : lui n'est pas notifié, le magasinier l'est.
    client.force_login(admin_a)
    client.post(reverse("inventory:wo_request_part", args=[work_order.pk]), {"item": "ROU-6205", "quantity": "2"})
    part = notes(keeper, K.PART).get()
    assert "ROU-6205" in part.body and part.url == reverse("inventory:request_queue")
    assert not notes(admin_a, K.PART).exists()
    record(setup_a, "5.0")
    assert notes(admin_a, K.ALERT).count() == 1 and not notes(keeper, K.ALERT).exists()


@pytest.mark.django_db
def test_bell_list_open_and_isolation(client, tenant_a, tenant_b, admin_a, admin_b, equipment_a):
    with tenant_context(tenant_a):
        mine = Notification.objects.create(user=admin_a, kind=K.TO_VALIDATE, title="OT terminé à valider", url=equipment_a.get_absolute_url())
        Notification.objects.create(user=admin_a, kind=K.REQUEST, title="Demande", url="https://exemple.com/piege")
    client.force_login(admin_a)
    home = client.get(reverse("dashboard:home"))
    assert home.context["notif_unread_count"] == 2 and "OT terminé à valider" in home.content.decode()
    response = client.get(reverse("notifications:open", args=[mine.pk]))
    assert response.status_code == 302 and response["Location"] == equipment_a.get_absolute_url()
    assert Notification.all_tenants.get(pk=mine.pk).read_at is not None
    other = Notification.all_tenants.exclude(pk=mine.pk).get()
    assert client.get(reverse("notifications:open", args=[other.pk]))["Location"] == reverse("notifications:list")  # lien externe refusé
    assert client.get(reverse("notifications:list")).status_code == 200
    client.force_login(admin_b)
    assert client.get(reverse("notifications:open", args=[mine.pk])).status_code == 404
    client.force_login(admin_a)
    with tenant_context(tenant_a):
        Notification.objects.create(user=admin_a, kind=K.ALERT, title="Alerte")
    client.post(reverse("notifications:read_all"))
    assert not Notification.all_tenants.filter(user=admin_a, read_at__isnull=True).exists()


@pytest.mark.django_db
def test_purge_keeps_recent_notifications(tenant_a, admin_a):
    with tenant_context(tenant_a):
        old_read = Notification.objects.create(user=admin_a, kind=K.ALERT, title="Ancienne lue", read_at=timezone.now())
        old_unread = Notification.objects.create(user=admin_a, kind=K.ALERT, title="Ancienne non lue")
        recent = Notification.objects.create(user=admin_a, kind=K.ALERT, title="Récente", read_at=timezone.now())
    Notification.all_tenants.filter(pk=old_read.pk).update(created_at=timezone.now() - timedelta(days=120))
    Notification.all_tenants.filter(pk=old_unread.pk).update(created_at=timezone.now() - timedelta(days=120))
    assert purge() == 1
    assert set(Notification.all_tenants.values_list("pk", flat=True)) == {old_unread.pk, recent.pk}
