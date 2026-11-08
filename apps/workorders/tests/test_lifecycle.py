"""Cycle de vie des demandes et des OT : transitions, droits, arrêts, temps et coûts."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.assets.models import Equipment
from apps.core.tenancy import tenant_context
from apps.workforce.models import Technician
from apps.workorders import services
from apps.workorders.models import (
    Downtime,
    Expense,
    FailureCode,
    PartUsage,
    TimeEntry,
    WorkOrder,
    WorkRequest,
)
from conftest import make_user


def make_technician(tenant, user=None, number="T1", rate="12.5"):
    with tenant_context(tenant):
        technician = Technician.objects.create(
            employee_number=number, first_name="Karim", last_name=f"Tech{number}", hourly_rate=Decimal(rate), user=user,
        )
    if user is not None:
        user.refresh_from_db()  # vide le cache de la relation inverse user.technician
    return technician


@pytest.fixture
def manager_a(tenant_a):
    return make_user(tenant_a, "maintenance_manager", "manager_a")


@pytest.fixture
def tech_user(tenant_a):
    user = make_user(tenant_a, "technician", "karim")
    make_technician(tenant_a, user=user)
    user.refresh_from_db()
    return user


@pytest.fixture
def cause_a(tenant_a):
    with tenant_context(tenant_a):
        return FailureCode.objects.create(kind="cause", code="JOINT", name="Joint usé")


@pytest.mark.django_db
def test_request_with_stop_marks_equipment_broken_and_opens_downtime(tenant_a, manager_a, equipment_a):
    with tenant_context(tenant_a):
        request_obj = services.create_request(
            user=manager_a, equipment=equipment_a, description="Fuite d'huile\nvérin", priority=1, production_stopped=True,
        )
        equipment_a.refresh_from_db()
        assert request_obj.number.startswith("DI-") and request_obj.number.endswith("000001")
        assert equipment_a.status == Equipment.Status.BROKEN
        assert Downtime.objects.filter(work_request=request_obj, ended_at__isnull=True).count() == 1

        work_order = services.accept_request(request_obj, user=manager_a)
        assert work_order.status == WorkOrder.Status.TO_PLAN
        assert work_order.title == "Fuite d'huile"
        assert work_order.due_date == timezone.localdate()  # P1 : échéance le jour même
        assert Downtime.objects.get(work_request=request_obj).work_order == work_order
        request_obj.refresh_from_db()
        assert request_obj.status == WorkRequest.Status.ACCEPTED
        with pytest.raises(ValidationError):
            services.accept_request(request_obj, user=manager_a)


@pytest.mark.django_db
def test_rejected_request_closes_downtime_and_restores_equipment(tenant_a, manager_a, equipment_a):
    with tenant_context(tenant_a):
        request_obj = services.create_request(user=manager_a, equipment=equipment_a, description="Bruit", priority=3, production_stopped=True)
        with pytest.raises(ValidationError):
            services.reject_request(request_obj, user=manager_a, note="")
        services.reject_request(request_obj, user=manager_a, note="Fonctionnement normal")
        equipment_a.refresh_from_db()
        assert equipment_a.status == Equipment.Status.IN_SERVICE
        assert not Downtime.objects.filter(ended_at__isnull=True).exists()


@pytest.mark.django_db
def test_full_corrective_cycle_with_frozen_costs(tenant_a, manager_a, tech_user, equipment_a, cause_a):
    with tenant_context(tenant_a):
        technician = tech_user.technician
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="Fuite vérin", kind="corrective", priority=2,
            production_stopped=True, technicians=[technician],
        )
        assert work_order.status == WorkOrder.Status.ASSIGNED
        equipment_a.refresh_from_db()
        assert equipment_a.status == Equipment.Status.BROKEN

        services.start_timer(work_order, user=tech_user)
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.IN_PROGRESS and work_order.started_at is not None
        assert TimeEntry.objects.filter(work_order=work_order, ended_at__isnull=True).count() == 1
        services.stop_timer(work_order, user=tech_user)

        with pytest.raises(ValidationError):
            services.finish(work_order, user=tech_user)  # compte rendu et cause manquants

        start = timezone.now() - timedelta(hours=3)
        services.add_time_entry(work_order, user=tech_user, technician=technician, started_at=start, ended_at=start + timedelta(hours=2))
        PartUsage.objects.create(work_order=work_order, designation="Kit joints", quantity=Decimal("2"), unit_cost=Decimal("3.5"))
        Expense.objects.create(work_order=work_order, nature="external", label="Rectification tige", amount=Decimal("100"))
        work_order.work_done, work_order.failure_cause = "Remplacement des joints", cause_a
        work_order.save()

        services.finish(work_order, user=tech_user)
        work_order.refresh_from_db()
        equipment_a.refresh_from_db()
        assert work_order.status == WorkOrder.Status.DONE
        assert equipment_a.status == Equipment.Status.IN_SERVICE
        assert not work_order.downtimes.filter(ended_at__isnull=True).exists()

        with pytest.raises(PermissionDenied):
            services.validate(work_order, user=tech_user)
        services.validate(work_order, user=manager_a)
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.VALIDATED
        assert work_order.parts_cost == Decimal("7.000")
        assert work_order.external_cost == Decimal("100.000")
        assert work_order.labour_cost >= Decimal("25.000")  # 2 h × 12,5 + le temps (quasi nul) du chronomètre
        assert work_order.total_cost == work_order.labour_cost + Decimal("107.000")
        assert [log.to_status for log in work_order.status_logs.all()] == ["assigned", "in_progress", "done", "validated"]


@pytest.mark.django_db
def test_checklist_must_be_completed_before_finishing(tenant_a, manager_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="Graissage", kind="preventive", priority=3, technicians=[tech_user.technician],
        )
        work_order.checklist.create(label="Graisser les paliers", position=1)
        services.start_timer(work_order, user=tech_user)
        work_order.work_done = "Graissage fait"
        work_order.save()
        assert any("check-list" in str(m) for m in services.finish_requirements(work_order))
        with pytest.raises(ValidationError):
            services.finish(work_order, user=tech_user)
        work_order.checklist.update(is_done=True)
        services.finish(work_order, user=tech_user)  # préventif : pas de cause exigée
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.DONE


@pytest.mark.django_db
def test_technician_cannot_work_on_someone_elses_order(tenant_a, manager_a, tech_user, equipment_a):
    other = make_technician(tenant_a, number="T2")
    with tenant_context(tenant_a):
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="Contrôle", kind="corrective", priority=3, technicians=[other],
        )
        with pytest.raises(PermissionDenied):
            services.start_timer(work_order, user=tech_user)


@pytest.mark.django_db
def test_invalid_transitions_are_refused(tenant_a, manager_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="X", kind="corrective", priority=3, technicians=[tech_user.technician],
        )
        with pytest.raises(ValidationError):
            services.validate(work_order, user=manager_a)
        with pytest.raises(ValidationError):
            services.resume(work_order, user=manager_a)
        with pytest.raises(ValidationError):
            services.cancel(work_order, user=manager_a, reason="")
        services.cancel(work_order, user=manager_a, reason="Doublon")
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.CANCELLED
        with pytest.raises(ValidationError):
            services.start_timer(work_order, user=tech_user)


@pytest.mark.django_db
def test_waiting_stops_timers_and_resume(tenant_a, manager_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="Roulement", kind="corrective", priority=2, technicians=[tech_user.technician],
        )
        services.start_timer(work_order, user=tech_user)
        with pytest.raises(ValidationError):
            services.put_on_hold(work_order, user=tech_user, action="wait_parts", reason="")
        services.put_on_hold(work_order, user=tech_user, action="wait_parts", reason="Roulement 6310 commandé")
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.WAITING_PARTS
        assert not TimeEntry.objects.filter(work_order=work_order, ended_at__isnull=True).exists()
        services.resume(work_order, user=tech_user)
        work_order.refresh_from_db()
        assert work_order.status == WorkOrder.Status.IN_PROGRESS and work_order.waiting_reason == ""


@pytest.mark.django_db
def test_only_one_running_timer_per_technician(tenant_a, manager_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        technician = tech_user.technician
        first = services.create_work_order(user=manager_a, equipment=equipment_a, title="A", kind="corrective", priority=3, technicians=[technician])
        second = services.create_work_order(user=manager_a, equipment=equipment_a, title="B", kind="corrective", priority=3, technicians=[technician])
        services.start_timer(first, user=tech_user)
        services.start_timer(second, user=tech_user)
        running = TimeEntry.objects.filter(technician=technician, ended_at__isnull=True)
        assert list(running.values_list("work_order_id", flat=True)) == [second.pk]


@pytest.mark.django_db
def test_technician_creating_urgent_order_is_assigned_to_it(tenant_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(user=tech_user, equipment=equipment_a, title="Urgence", kind="corrective", priority=1)
        assert work_order.status == WorkOrder.Status.ASSIGNED
        assert list(work_order.technicians.all()) == [tech_user.technician]


@pytest.mark.django_db
def test_manual_time_entry_rules(tenant_a, manager_a, tech_user, equipment_a):
    with tenant_context(tenant_a):
        work_order = services.create_work_order(
            user=manager_a, equipment=equipment_a, title="X", kind="corrective", priority=3, technicians=[tech_user.technician],
        )
        now = timezone.now()
        with pytest.raises(ValidationError):
            services.add_time_entry(work_order, user=manager_a, technician=tech_user.technician, started_at=now, ended_at=now - timedelta(hours=1))
        with pytest.raises(ValidationError):
            services.add_time_entry(work_order, user=manager_a, technician=tech_user.technician, started_at=now, ended_at=now + timedelta(hours=2))
        entry = services.add_time_entry(
            work_order, user=manager_a, technician=tech_user.technician,
            started_at=now - timedelta(hours=2, minutes=30), ended_at=now, is_overtime=True,
        )
        assert entry.hours == Decimal("2.50")
        assert entry.hourly_rate == Decimal("12.500")  # pas de taux HS défini : taux normal
