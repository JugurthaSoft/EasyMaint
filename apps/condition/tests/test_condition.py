"""Conditionnel : niveaux, seuils versionnés, alertes, règles, saisie, droits et isolation."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.condition import services
from apps.condition.models import (
    Alert,
    Level,
    Measurement,
    MeasurementPoint,
    MeasurementSession,
    Parameter,
    Threshold,
    TriggerRule,
)
from apps.core.tenancy import tenant_context
from apps.workorders.models import WorkOrder, WorkRequest
from conftest import make_equipment, make_user

D = Decimal


@pytest.fixture
def setup_a(tenant_a, equipment_a):
    """Un point avec une vitesse vibratoire (seuils hauts) et une viscosité (plage)."""
    with tenant_context(tenant_a):
        vel = Parameter.objects.create(code="VIB-V", name="Vitesse vibratoire", unit="mm/s", category="vibration")
        visc = Parameter.objects.create(code="VISC", name="Viscosité", unit="cSt", category="oil", direction="range")
        point = MeasurementPoint.objects.create(equipment=equipment_a, code="P1", name="Palier moteur")
        point.parameters.set([vel, visc])
        Threshold.objects.create(point=point, parameter=vel, valid_from=timezone.localdate() - timedelta(days=400),
                                 warning_high=D("2.8"), alarm_high=D("4.5"), critical_high=D("7.1"))
        Threshold.objects.create(point=point, parameter=visc, valid_from=timezone.localdate() - timedelta(days=400),
                                 warning_low=D("198"), alarm_low=D("187"), warning_high=D("242"), alarm_high=D("253"))
    return {"vel": vel, "visc": visc, "point": point, "equipment": equipment_a, "tenant": tenant_a}


def record(s, value, *, days_ago=0, parameter="vel"):
    with tenant_context(s["tenant"]):
        return services.record_session(
            equipment=s["equipment"], kind="vibration", measured_at=timezone.now() - timedelta(days=days_ago, minutes=1),
            values=[(s["point"], s[parameter], D(str(value)))],
        )


def test_levels_on_both_sides():
    t = Threshold(warning_high=D("2.8"), alarm_high=D("4.5"), critical_high=D("7.1"), warning_low=D("1"))
    assert [t.level_for(v) for v in ("2.0", "2.8", "4.6", "7.1", "0.9")] == ["normal", "warning", "alarm", "critical", "warning"]


@pytest.mark.django_db
def test_threshold_order_is_validated(setup_a):
    with tenant_context(setup_a["tenant"]):
        bad = Threshold(point=setup_a["point"], parameter=setup_a["vel"], warning_high=D("5"), alarm_high=D("4"))
        with pytest.raises(ValidationError):
            bad.full_clean()
        empty = Threshold(point=setup_a["point"], parameter=setup_a["vel"])
        with pytest.raises(ValidationError):
            empty.full_clean()
        low = Threshold(point=setup_a["point"], parameter=setup_a["visc"], warning_low=D("190"), alarm_low=D("195"))
        with pytest.raises(ValidationError):
            low.full_clean()


@pytest.mark.django_db
def test_measurements_use_threshold_valid_at_their_date(setup_a):
    today = timezone.localdate()
    with tenant_context(setup_a["tenant"]):
        Threshold.objects.create(point=setup_a["point"], parameter=setup_a["vel"], valid_from=today - timedelta(days=10),
                                 warning_high=D("2"), alarm_high=D("3"), critical_high=D("4"))
    old = record(setup_a, "3.5", days_ago=20)  # ancien seuil : attention
    new = record(setup_a, "3.5", days_ago=0)   # nouveau seuil : alarme
    assert Measurement.all_tenants.get(session=old).level == Level.WARNING
    assert Measurement.all_tenants.get(session=new).level == Level.ALARM


@pytest.mark.django_db
def test_no_threshold_means_no_alert(tenant_a, equipment_a):
    with tenant_context(tenant_a):
        temp = Parameter.objects.create(code="TEMP", name="Température", unit="°C", category="temperature")
        point = MeasurementPoint.objects.create(equipment=equipment_a, code="T1", name="Huile")
        point.parameters.set([temp])
        services.record_session(equipment=equipment_a, kind="inspection", measured_at=timezone.now() - timedelta(minutes=1),
                                values=[(point, temp, D("90"))])
        assert Measurement.objects.get().level == Level.UNKNOWN
        assert not Alert.objects.exists()


@pytest.mark.django_db
def test_one_alert_per_point_and_parameter(setup_a):
    record(setup_a, "3.0", days_ago=3)
    record(setup_a, "5.0", days_ago=2)
    record(setup_a, "2.0", days_ago=1)
    with tenant_context(setup_a["tenant"]):
        alert = Alert.objects.get()
        assert alert.level == Level.NORMAL and alert.max_level == Level.ALARM
        assert alert.back_to_normal and alert.is_active
        assert alert.first_measurement.value == D("3.0") and alert.last_measurement.value == D("2.0")


@pytest.mark.django_db
def test_late_entry_of_an_older_measurement_does_not_change_the_alert(setup_a):
    record(setup_a, "3.0", days_ago=1)
    record(setup_a, "9.0", days_ago=5)  # saisie après coup d'une mesure plus ancienne
    with tenant_context(setup_a["tenant"]):
        alert = Alert.objects.get()
        assert alert.level == Level.WARNING and alert.max_level == Level.WARNING


@pytest.mark.django_db
def test_range_parameter_alerts_on_both_sides(setup_a):
    record(setup_a, "185", parameter="visc")
    with tenant_context(setup_a["tenant"]):
        assert Alert.objects.get(parameter=setup_a["visc"]).level == Level.ALARM


@pytest.mark.django_db
def test_rule_creates_a_single_request(setup_a):
    with tenant_context(setup_a["tenant"]):
        TriggerRule.objects.create(name="Vibration alarme", parameter=setup_a["vel"], min_level="alarm", consecutive=1, action="request", priority=2)
    record(setup_a, "3.0", days_ago=3)
    with tenant_context(setup_a["tenant"]):
        assert not WorkRequest.objects.exists()
    record(setup_a, "5.0", days_ago=2)
    record(setup_a, "6.0", days_ago=1)
    with tenant_context(setup_a["tenant"]):
        request_obj = WorkRequest.objects.get()
        assert request_obj.requested_by is None and request_obj.priority == 2
        assert "Vibration alarme" in request_obj.description
        alert = Alert.objects.get()
        assert alert.work_request == request_obj and alert.rule.name == "Vibration alarme"


@pytest.mark.django_db
def test_rule_with_consecutive_measurements_creates_work_order(setup_a):
    with tenant_context(setup_a["tenant"]):
        TriggerRule.objects.create(name="Deux attentions", parameter=setup_a["vel"], min_level="warning", consecutive=2, action="work_order", priority=3)
    record(setup_a, "3.0", days_ago=2)
    with tenant_context(setup_a["tenant"]):
        assert not WorkOrder.objects.exists()
    record(setup_a, "3.2", days_ago=1)
    with tenant_context(setup_a["tenant"]):
        wo = WorkOrder.objects.get()
        assert wo.kind == WorkOrder.Kind.CONDITIONAL and wo.equipment == setup_a["equipment"]
        assert wo.status_logs.first().comment.startswith("Créé par la règle")


@pytest.mark.django_db
def test_rule_for_another_equipment_is_ignored(setup_a):
    other = make_equipment(setup_a["tenant"], "OTHER-1")
    with tenant_context(setup_a["tenant"]):
        TriggerRule.objects.create(name="Autre machine", parameter=setup_a["vel"], equipment=other, min_level="warning", action="request")
    record(setup_a, "8.0")
    with tenant_context(setup_a["tenant"]):
        assert not WorkRequest.objects.exists()


@pytest.mark.django_db
def test_record_session_validations(setup_a):
    other = make_equipment(setup_a["tenant"], "OTHER-2")
    s = setup_a
    with tenant_context(s["tenant"]):
        with pytest.raises(ValidationError):
            services.record_session(equipment=other, kind="inspection", measured_at=timezone.now(), values=[(s["point"], s["vel"], D("1"))])
        with pytest.raises(ValidationError):
            services.record_session(equipment=s["equipment"], kind="inspection", measured_at=timezone.now(), values=[(s["point"], s["vel"], None)])
        with pytest.raises(ValidationError):
            services.record_session(equipment=s["equipment"], kind="inspection", measured_at=timezone.now() + timedelta(days=1),
                                    values=[(s["point"], s["vel"], D("1"))])
        temp = Parameter.objects.create(code="TEMP", name="Température", unit="°C")
        with pytest.raises(ValidationError):
            services.record_session(equipment=s["equipment"], kind="inspection", measured_at=timezone.now(), values=[(s["point"], temp, D("1"))])
        assert not MeasurementSession.objects.exists()


def test_parse_value():
    assert services.parse_value("4,5") == D("4.5")
    assert services.parse_value(" 1 234,5 ") == D("1234.5")
    assert services.parse_value("") is None
    with pytest.raises(ValidationError):
        services.parse_value("abc")


@pytest.mark.django_db
def test_acknowledge_close_and_create_work_order(setup_a, admin_a):
    record(setup_a, "5.0")
    with tenant_context(setup_a["tenant"]):
        alert = Alert.objects.get()
        services.acknowledge(alert, user=admin_a, comment="Vu")
        with pytest.raises(ValidationError):
            services.acknowledge(alert, user=admin_a)
        wo = services.create_work_order_from_alert(alert, user=admin_a)
        assert wo.kind == WorkOrder.Kind.CONDITIONAL and wo.priority == 2
        with pytest.raises(ValidationError):
            services.create_work_order_from_alert(alert, user=admin_a)
        with pytest.raises(ValidationError):
            services.close(alert, user=admin_a, comment=" ")
        services.close(alert, user=admin_a, comment="Roulement remplacé")
        alert.refresh_from_db()
        assert alert.status == Alert.Status.CLOSED
    # Une nouvelle dérive ouvre une nouvelle alerte
    record(setup_a, "5.5")
    with tenant_context(setup_a["tenant"]):
        assert Alert.objects.exclude(status="closed").count() == 1


@pytest.mark.django_db
def test_chart_series(setup_a):
    record(setup_a, "2.0", days_ago=2)
    record(setup_a, "3.0", days_ago=1)
    with tenant_context(setup_a["tenant"]):
        series = services.chart_series(setup_a["point"], setup_a["vel"])
    assert series["values"] == [2.0, 3.0] and series["levels"] == ["normal", "warning"]
    assert series["alarm_high"] == [4.5, 4.5] and series["warning_low"] == []


# --- Écrans -----------------------------------------------------------------------------------

def _grid_post(s, value, kind="inspection"):
    measured = (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return {"kind": kind, "measured_at": measured, f"v-{s['point'].pk}-{s['vel'].pk}": value, f"v-{s['point'].pk}-{s['visc'].pk}": ""}


@pytest.mark.django_db
def test_technician_records_measurements_from_the_grid(client, setup_a, technician_a):
    client.force_login(technician_a)
    url = reverse("condition:session_create", args=[setup_a["equipment"].pk])
    assert client.get(url, {"type": "vibration"}).status_code == 200
    response = client.post(url, _grid_post(setup_a, "5,2"))
    session = MeasurementSession.all_tenants.get()
    assert response.status_code == 302 and response["Location"] == session.get_absolute_url()
    measurement = Measurement.all_tenants.get()
    assert measurement.value == D("5.2") and measurement.level == Level.ALARM
    assert session.created_by == technician_a
    assert client.get(session.get_absolute_url()).status_code == 200


@pytest.mark.django_db
def test_invalid_value_is_refused_without_saving(client, setup_a, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("condition:session_create", args=[setup_a["equipment"].pk]), _grid_post(setup_a, "abc"))
    assert response.status_code == 200
    assert not MeasurementSession.all_tenants.exists()


@pytest.mark.django_db
def test_technician_permissions(client, setup_a, technician_a):
    record(setup_a, "5.0")
    alert = Alert.all_tenants.get()
    client.force_login(technician_a)
    assert client.get(reverse("condition:point_create", args=[setup_a["equipment"].pk])).status_code == 403
    response = client.post(reverse("condition:threshold_save", args=[setup_a["point"].pk, setup_a["vel"].pk]), {})
    assert response.status_code == 403
    assert client.post(reverse("condition:alert_action", args=[alert.pk, "clore"]), {"comment": "x"}).status_code == 403
    client.post(reverse("condition:alert_action", args=[alert.pk, "acquitter"]), {"comment": ""})
    alert.refresh_from_db()
    assert alert.status == Alert.Status.ACKNOWLEDGED


@pytest.mark.django_db
def test_threshold_form_creates_a_new_version(client, setup_a, admin_a):
    client.force_login(admin_a)
    prefix = f"p{setup_a['vel'].pk}"
    response = client.post(reverse("condition:threshold_save", args=[setup_a["point"].pk, setup_a["vel"].pk]), {
        f"{prefix}-warning_high": "3", f"{prefix}-alarm_high": "5", f"{prefix}-critical_high": "8",
        f"{prefix}-source": "manufacturer", f"{prefix}-reference": "Notice", f"{prefix}-valid_from": timezone.localdate().isoformat(),
    })
    assert response.status_code == 302
    assert Threshold.all_tenants.filter(point=setup_a["point"], parameter=setup_a["vel"]).count() == 2
    with tenant_context(setup_a["tenant"]):
        current = services.threshold_for(setup_a["point"], setup_a["vel"], timezone.localdate())
    assert current.alarm_high == D("5")


@pytest.mark.django_db
def test_pages_render_and_isolation(client, setup_a, admin_a, admin_b):
    record(setup_a, "2.0", days_ago=1)
    record(setup_a, "5.0")
    alert = Alert.all_tenants.get()
    session = MeasurementSession.all_tenants.first()
    client.force_login(admin_a)
    for url in (
        reverse("condition:overview"), reverse("condition:parameter_list"), reverse("condition:session_list"),
        reverse("condition:alert_list"), reverse("condition:rule_list"), reverse("condition:rule_create"),
        reverse("condition:parameter_create"), reverse("condition:point_create", args=[setup_a["equipment"].pk]),
        setup_a["point"].get_absolute_url(), reverse("condition:point_update", args=[setup_a["point"].pk]),
        alert.get_absolute_url(), session.get_absolute_url(),
    ):
        assert client.get(url).status_code == 200, url
    response = client.get(reverse("assets:equipment_detail", args=[setup_a["equipment"].pk]), {"onglet": "mesures"})
    assert response.status_code == 200 and len(response.context["condition_rows"]) == 1
    response = client.get(reverse("dashboard:home"))
    assert response.context["condition_alert_count"] == 1
    response = client.get(reverse("core:search"), {"q": "Palier"})
    assert any("Palier" in r.title for r in response.context["results"])
    client.force_login(admin_b)
    assert client.get(setup_a["point"].get_absolute_url()).status_code == 404
    assert client.get(alert.get_absolute_url()).status_code == 404
    assert list(client.get(reverse("condition:alert_list")).context["alerts"]) == []


@pytest.mark.django_db
def test_create_point_and_rule(client, admin_a, tenant_a, equipment_a):
    with tenant_context(tenant_a):
        vel = Parameter.objects.create(code="VIB-V", name="Vitesse vibratoire", unit="mm/s", category="vibration")
    client.force_login(admin_a)
    response = client.post(reverse("condition:point_create", args=[equipment_a.pk]), {
        "code": "p-ca", "name": "Palier CA", "position": "", "direction": "H", "parameters": [vel.pk], "notes": "", "is_active": "on",
    })
    point = MeasurementPoint.all_tenants.get()
    assert response.status_code == 302 and point.code == "P-CA" and point.equipment == equipment_a
    response = client.post(reverse("condition:point_create", args=[equipment_a.pk]), {
        "code": "P-CA", "name": "Doublon", "direction": "", "parameters": [vel.pk],
    })
    assert response.status_code == 200 and "code" in response.context["form"].errors
    response = client.post(reverse("condition:rule_create"), {
        "name": "Vib alarme", "parameter": vel.pk, "equipment": "", "min_level": "alarm", "consecutive": "1",
        "action": "request", "priority": "2", "is_active": "on",
    })
    assert response.status_code == 302 and TriggerRule.all_tenants.count() == 1


@pytest.mark.django_db
def test_production_manager_can_view_but_not_record(client, tenant_a, setup_a):
    production = make_user(tenant_a, "production_manager", "prod_cond")
    client.force_login(production)
    assert client.get(reverse("condition:overview")).status_code == 200
    assert client.get(reverse("condition:session_create", args=[setup_a["equipment"].pk])).status_code == 403


@pytest.mark.django_db
def test_point_form_groups_parameters_by_category(client, admin_a, tenant_a, equipment_a):
    with tenant_context(tenant_a):
        Parameter.objects.create(code="COUR", name="Intensité électrique", unit="A", category="current")
        Parameter.objects.create(code="FE", name="Fer (Fe)", unit="ppm", category="oil")
        Parameter.objects.create(code="VIB-V", name="Vitesse vibratoire", unit="mm/s", category="vibration")
        Parameter.objects.create(code="VIB-A", name="Accélération vibratoire", unit="m/s²", category="vibration")
    client.force_login(admin_a)
    response = client.get(reverse("condition:point_create", args=[equipment_a.pk]))
    groups = response.context["form"].parameter_groups()
    assert [str(label) for label, _items in groups] == ["Analyse vibratoire", "Analyse d'huile", "Intensité électrique"]
    assert [label for _pk, label, _checked in groups[0][1]] == ["Accélération vibratoire (m/s²)", "Vitesse vibratoire (mm/s)"]
