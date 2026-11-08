"""Préventif : échéances, génération, recalcul, report, indicateurs, écrans."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.assets.models import Equipment, Meter
from apps.assets.services import record_reading
from apps.core.tenancy import tenant_context
from apps.preventive import selectors, services
from apps.preventive.models import PlanChecklistItem, PreventivePlan
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder
from conftest import make_equipment, make_user

TODAY = timezone.localdate


def make_plan(tenant, equipment, code="PP-1", **fields):
    defaults = {
        "name": "Graissage", "operations": "Graisser les paliers", "trigger_mode": "calendar",
        "period_value": 1, "period_unit": "month", "next_due_date": TODAY() + timedelta(days=5), "lead_days": 7,
    }
    defaults.update(fields)
    with tenant_context(tenant):
        plan = PreventivePlan.objects.create(code=code, equipment=equipment, **defaults)
        PlanChecklistItem.objects.create(plan=plan, label="Graisser le palier 1", position=1)
        PlanChecklistItem.objects.create(plan=plan, label="Graisser le palier 2", position=2)
    return plan


@pytest.fixture
def meter_a(tenant_a, equipment_a):
    with tenant_context(tenant_a):
        return Meter.objects.create(equipment=equipment_a, name="Heures", kind="hours")


def test_add_period_handles_month_ends_and_years():
    assert services.add_period(date(2026, 1, 31), 1, "month") == date(2026, 2, 28)
    assert services.add_period(date(2028, 1, 31), 1, "month") == date(2028, 2, 29)
    assert services.add_period(date(2026, 11, 15), 3, "month") == date(2027, 2, 15)
    assert services.add_period(date(2026, 11, 15), 2, "week") == date(2026, 11, 29)
    assert services.add_period(date(2024, 2, 29), 1, "year") == date(2025, 2, 28)


@pytest.mark.django_db
def test_calendar_plan_generates_once_within_lead_time(tenant_a, equipment_a):
    plan = make_plan(tenant_a, equipment_a)
    with tenant_context(tenant_a):
        created = services.generate_due_work_orders()
        assert len(created) == 1
        wo = created[0]
        assert wo.kind == WorkOrder.Kind.PREVENTIVE and wo.preventive_plan == plan
        assert wo.due_date == wo.original_due_date == plan.next_due_date
        assert wo.status == WorkOrder.Status.TO_PLAN  # aucun intervenant sur le plan
        assert list(wo.checklist.values_list("label", flat=True)) == ["Graisser le palier 1", "Graisser le palier 2"]
        assert wo.number.startswith("OT-")
        # Jamais deux OT en attente pour le même plan
        assert services.generate_due_work_orders() == []


@pytest.mark.django_db
def test_not_generated_before_lead_time_or_when_inactive(tenant_a, equipment_a):
    make_plan(tenant_a, equipment_a, "PP-LOIN", next_due_date=TODAY() + timedelta(days=30), lead_days=7)
    make_plan(tenant_a, equipment_a, "PP-OFF", is_active=False)
    with tenant_context(tenant_a):
        assert services.generate_due_work_orders() == []


@pytest.mark.django_db
def test_retired_equipment_is_skipped(tenant_a):
    retired = make_equipment(tenant_a, "OLD-1", status=Equipment.Status.RETIRED)
    make_plan(tenant_a, retired)
    with tenant_context(tenant_a):
        assert services.generate_due_work_orders() == []


@pytest.mark.django_db
def test_validation_recalculates_next_due_fixed_and_floating(tenant_a, admin_a, equipment_a):
    fixed = make_plan(tenant_a, equipment_a, "PP-FIX", next_due_date=TODAY() - timedelta(days=2))
    floating = make_plan(tenant_a, equipment_a, "PP-GLI", next_due_date=TODAY() - timedelta(days=2), schedule_basis="floating")
    with tenant_context(tenant_a):
        orders = {wo.preventive_plan_id: wo for wo in services.generate_due_work_orders()}
        assert set(orders) == {fixed.pk, floating.pk}
        for wo in orders.values():
            WorkOrder.objects.filter(pk=wo.pk).update(status=WorkOrder.Status.DONE, finished_at=timezone.now())
            wo.refresh_from_db()
            wo_services.validate(wo, user=admin_a)  # le signal recalcule l'échéance
        fixed.refresh_from_db()
        floating.refresh_from_db()
        assert fixed.next_due_date == services.add_period(TODAY() - timedelta(days=2), 1, "month")
        assert floating.next_due_date == services.add_period(TODAY(), 1, "month")
        assert fixed.last_done_date == TODAY()
        # Plus d'OT en attente : le suivant sera généré à la prochaine échéance seulement
        assert services.generate_due_work_orders() == []


@pytest.mark.django_db
def test_fixed_schedule_skips_missed_periods(tenant_a, equipment_a):
    plan = make_plan(tenant_a, equipment_a, period_value=1, period_unit="week", next_due_date=TODAY() - timedelta(days=20))
    with tenant_context(tenant_a):
        wo = services.generate_due_work_orders()[0]
        WorkOrder.objects.filter(pk=wo.pk).update(status=WorkOrder.Status.VALIDATED, finished_at=timezone.now())
        wo.refresh_from_db()
        services.on_work_order_closed(wo, "validated")
        plan.refresh_from_db()
        assert TODAY() < plan.next_due_date <= TODAY() + timedelta(days=7)


@pytest.mark.django_db
def test_cancelled_order_skips_the_occurrence(tenant_a, admin_a, equipment_a):
    plan = make_plan(tenant_a, equipment_a, next_due_date=TODAY() + timedelta(days=3))
    with tenant_context(tenant_a):
        wo = services.generate_due_work_orders()[0]
        wo_services.cancel(wo, user=admin_a, reason="Machine à l'arrêt pour travaux")
        plan.refresh_from_db()
        assert plan.next_due_date == services.add_period(TODAY() + timedelta(days=3), 1, "month")
        assert plan.last_done_date is None


@pytest.mark.django_db
def test_meter_plan_triggers_at_threshold_minus_lead(tenant_a, equipment_a, meter_a):
    plan = make_plan(
        tenant_a, equipment_a, "PP-CPT", trigger_mode="meter", meter=meter_a, meter_interval=Decimal("500"),
        meter_lead=Decimal("50"), last_done_meter=Decimal("0"), next_due_date=None,
    )
    with tenant_context(tenant_a):
        Meter.objects.filter(pk=meter_a.pk).update(current_value=Decimal("440"))
        assert services.generate_due_work_orders() == []
        Meter.objects.filter(pk=meter_a.pk).update(current_value=Decimal("460"))
        created = services.generate_due_work_orders()
        assert len(created) == 1
        assert created[0].due_date == TODAY()  # usage inconnu : échéance le jour même
        wo = created[0]
        WorkOrder.objects.filter(pk=wo.pk).update(status=WorkOrder.Status.VALIDATED, finished_at=timezone.now())
        wo.refresh_from_db()
        services.on_work_order_closed(wo, "validated")
        plan.refresh_from_db()
        assert plan.last_done_meter == Decimal("460")
        assert plan.next_meter_threshold == Decimal("960")


@pytest.mark.django_db
def test_combined_plan_first_threshold_wins(tenant_a, equipment_a, meter_a):
    make_plan(
        tenant_a, equipment_a, "PP-MIX", trigger_mode="both", next_due_date=TODAY() + timedelta(days=100),
        meter=meter_a, meter_interval=Decimal("100"), meter_lead=Decimal("0"), last_done_meter=Decimal("0"),
    )
    with tenant_context(tenant_a):
        assert services.generate_due_work_orders() == []
        Meter.objects.filter(pk=meter_a.pk).update(current_value=Decimal("120"))
        created = services.generate_due_work_orders()
        assert len(created) == 1 and created[0].due_date == TODAY()


@pytest.mark.django_db
def test_meter_reading_triggers_generation(tenant_a, equipment_a, meter_a, django_capture_on_commit_callbacks):
    plan = make_plan(
        tenant_a, equipment_a, "PP-REL", trigger_mode="meter", meter=meter_a, meter_interval=Decimal("500"),
        meter_lead=Decimal("0"), last_done_meter=Decimal("0"), next_due_date=None,
    )
    with django_capture_on_commit_callbacks(execute=True):
        with tenant_context(tenant_a):
            record_reading(meter_a, Decimal("510"), reading_at=timezone.now() - timedelta(minutes=1))
    assert WorkOrder.all_tenants.filter(preventive_plan=plan).count() == 1


@pytest.mark.django_db
def test_postpone_keeps_original_due_date(tenant_a, admin_a, technician_a, equipment_a):
    make_plan(tenant_a, equipment_a, next_due_date=TODAY() + timedelta(days=3))
    with tenant_context(tenant_a):
        wo = services.generate_due_work_orders()[0]
        with pytest.raises(ValidationError):
            wo_services.postpone(wo, user=admin_a, new_date=TODAY() - timedelta(days=1), reason="x")
        with pytest.raises(ValidationError):
            wo_services.postpone(wo, user=admin_a, new_date=TODAY() + timedelta(days=10), reason=" ")
        with pytest.raises(PermissionDenied):
            wo_services.postpone(wo, user=technician_a, new_date=TODAY() + timedelta(days=10), reason="Pièces")
        wo_services.postpone(wo, user=admin_a, new_date=TODAY() + timedelta(days=10), reason="Arrêt de ligne prévu")
        wo.refresh_from_db()
        assert wo.due_date == wo.planned_date == TODAY() + timedelta(days=10)
        assert wo.original_due_date == TODAY() + timedelta(days=3)
        assert wo.is_postponed
        assert wo.status_logs.filter(comment__startswith="Reporté").exists()


@pytest.mark.django_db
def test_compliance_rates(tenant_a, tenant_b, equipment_a):
    now = timezone.now()
    rows = [
        ("V1", WorkOrder.Status.VALIDATED, TODAY(), now),                      # réalisé à l'heure
        ("V2", WorkOrder.Status.DONE, TODAY() - timedelta(days=5), now),       # réalisé en retard
        ("V3", WorkOrder.Status.ASSIGNED, TODAY() - timedelta(days=3), None),  # échu, non réalisé
        ("V4", WorkOrder.Status.CANCELLED, TODAY() - timedelta(days=1), None),  # annulé : non réalisé
        ("V5", WorkOrder.Status.VALIDATED, TODAY() - timedelta(days=60), now),  # hors période
    ]
    with tenant_context(tenant_a):
        for number, status, due, finished in rows:
            WorkOrder.objects.create(
                number=number, kind="preventive", equipment=equipment_a, title=number, status=status,
                due_date=due, original_due_date=due, finished_at=finished,
            )
        result = selectors.compliance(days=30)
    assert (result["due"], result["realized"], result["on_time"]) == (4, 2, 1)
    assert (result["realization_rate"], result["on_time_rate"]) == (50, 25)
    with tenant_context(tenant_b):
        assert selectors.compliance()["realization_rate"] is None


@pytest.mark.django_db
def test_projected_dates_skip_the_pending_occurrence(tenant_a, equipment_a):
    plan = make_plan(tenant_a, equipment_a, period_value=1, period_unit="week", next_due_date=TODAY() + timedelta(days=2))
    with tenant_context(tenant_a):
        assert services.projected_dates(plan, TODAY(), TODAY() + timedelta(days=20))[0] == TODAY() + timedelta(days=2)
        services.generate_due_work_orders()
        assert services.projected_dates(plan, TODAY(), TODAY() + timedelta(days=20))[0] == TODAY() + timedelta(days=9)


@pytest.mark.django_db
def test_generate_command_runs_for_every_tenant(tenant_a, tenant_b, equipment_a, equipment_b):
    make_plan(tenant_a, equipment_a)
    make_plan(tenant_b, equipment_b)
    call_command("generate_preventive")
    assert WorkOrder.all_tenants.filter(kind="preventive").count() == 2
    assert set(WorkOrder.all_tenants.values_list("tenant_id", flat=True)) == {tenant_a.pk, tenant_b.pk}


# --- Écrans -----------------------------------------------------------------------------

def _plan_post(equipment, **extra):
    data = {
        "code": "pp-new", "name": "Contrôle courroies", "equipment": equipment.pk, "operations": "Contrôler la tension",
        "priority": "3", "trigger_mode": "calendar", "period_value": "3", "period_unit": "month",
        "next_due_date": (TODAY() + timedelta(days=20)).isoformat(), "schedule_basis": "fixed", "lead_days": "7",
        "meter_lead": "0", "checklist_text": "Tension\nUsure\n\nAlignement", "is_active": "on",
    }
    data.update(extra)
    return data


@pytest.mark.django_db
def test_create_plan_with_checklist(client, admin_a, equipment_a, tenant_a):
    client.force_login(admin_a)
    response = client.post(reverse("preventive:plan_create"), _plan_post(equipment_a))
    assert response.status_code == 302, response.context["form"].errors if response.context else ""
    with tenant_context(tenant_a):
        plan = PreventivePlan.objects.get(code="PP-NEW")
        assert list(plan.checklist.values_list("label", flat=True)) == ["Tension", "Usure", "Alignement"]
        assert plan.trigger_summary == "Tous les 3 mois"


@pytest.mark.django_db
def test_plan_form_rules(client, admin_a, tenant_a, equipment_a):
    other = make_equipment(tenant_a, "EQ-2")
    with tenant_context(tenant_a):
        other_meter = Meter.objects.create(equipment=other, name="Heures", kind="hours")
    client.force_login(admin_a)
    response = client.post(reverse("preventive:plan_create"), _plan_post(equipment_a, period_value="", next_due_date=""))
    assert response.status_code == 200
    assert {"period_value", "next_due_date"} <= set(response.context["form"].errors)
    response = client.post(reverse("preventive:plan_create"), _plan_post(
        equipment_a, trigger_mode="meter", meter=other_meter.pk, meter_interval="500",
    ))
    assert response.status_code == 200 and "meter" in response.context["form"].errors


@pytest.mark.django_db
def test_meter_plan_starts_from_current_value(client, admin_a, tenant_a, equipment_a, meter_a):
    with tenant_context(tenant_a):
        Meter.objects.filter(pk=meter_a.pk).update(current_value=Decimal("1234"))
    client.force_login(admin_a)
    response = client.post(reverse("preventive:plan_create"), _plan_post(
        equipment_a, trigger_mode="meter", meter=meter_a.pk, meter_interval="500", meter_lead="20",
    ))
    assert response.status_code == 302
    with tenant_context(tenant_a):
        plan = PreventivePlan.objects.get(code="PP-NEW")
    assert plan.last_done_meter == Decimal("1234") and plan.next_meter_threshold == Decimal("1734")


@pytest.mark.django_db
def test_pages_render_and_are_isolated(client, admin_a, admin_b, equipment_a):
    plan = make_plan(equipment_a.tenant, equipment_a)
    client.force_login(admin_a)
    assert client.get(reverse("preventive:plan_list")).status_code == 200
    assert client.get(plan.get_absolute_url()).status_code == 200
    assert client.get(reverse("preventive:plan_create")).status_code == 200
    assert client.get(reverse("preventive:plan_update", args=[plan.pk])).status_code == 200
    for view in ("jour", "semaine", "mois"):
        response = client.get(reverse("preventive:planning"), {"vue": view})
        assert response.status_code == 200
    response = client.get(reverse("preventive:planning"), {"vue": "mois", "date": "pas-une-date"})
    assert response.status_code == 200
    client.force_login(admin_b)
    assert client.get(plan.get_absolute_url()).status_code == 404


@pytest.mark.django_db
def test_generate_now_button(client, admin_a, technician_a, tenant_a, equipment_a):
    plan = make_plan(tenant_a, equipment_a, next_due_date=TODAY() + timedelta(days=60))
    client.force_login(technician_a)
    assert client.get(reverse("preventive:plan_create")).status_code == 403
    assert client.post(reverse("preventive:plan_generate", args=[plan.pk])).status_code == 403
    client.force_login(admin_a)
    response = client.post(reverse("preventive:plan_generate", args=[plan.pk]))
    wo = WorkOrder.all_tenants.get(preventive_plan=plan)
    assert response["Location"] == wo.get_absolute_url()
    assert wo.due_date == TODAY() + timedelta(days=60)
    response = client.post(reverse("preventive:plan_generate", args=[plan.pk]))
    assert response["Location"] == plan.get_absolute_url()
    assert WorkOrder.all_tenants.filter(preventive_plan=plan).count() == 1


@pytest.mark.django_db
def test_postpone_view_and_work_order_page(client, admin_a, tenant_a, equipment_a):
    make_plan(tenant_a, equipment_a, next_due_date=TODAY() + timedelta(days=2))
    with tenant_context(tenant_a):
        wo = services.generate_due_work_orders()[0]
    client.force_login(admin_a)
    new_date = TODAY() + timedelta(days=9)
    client.post(reverse("preventive:wo_postpone", args=[wo.pk]), {"new_date": new_date.isoformat(), "reason": "Arrêt de ligne"})
    wo.refresh_from_db()
    assert wo.due_date == new_date and wo.original_due_date == TODAY() + timedelta(days=2)
    response = client.get(wo.get_absolute_url())
    assert response.status_code == 200
    assert response.context["wo"].is_postponed


@pytest.mark.django_db
def test_dashboard_and_equipment_show_preventive(client, admin_a, tenant_a, equipment_a):
    make_plan(tenant_a, equipment_a)
    client.force_login(admin_a)
    response = client.get(reverse("dashboard:home"))
    assert "preventive" in response.context
    response = client.get(reverse("assets:equipment_detail", args=[equipment_a.pk]))
    assert len(response.context["plans"]) == 1


@pytest.mark.django_db
def test_technician_sees_planning_but_not_plan_management(client, tenant_a):
    technician = make_user(tenant_a, "technician", "tech_planning")
    client.force_login(technician)
    assert client.get(reverse("preventive:planning")).status_code == 200
    assert client.get(reverse("preventive:plan_list")).status_code == 200
