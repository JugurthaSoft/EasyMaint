"""Indicateurs : temps requis, arrêts plafonnés, MTBF, MTTR, disponibilités, taux, écrans et droits."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.kpi import selectors
from apps.workorders import services as wo_services
from apps.workorders.models import Downtime, WorkOrder
from conftest import make_user

D = Decimal
MONDAY = date(2026, 3, 2)  # semaine du lundi 2 au dimanche 8 mars 2026


def at(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 3, day, hour, minute))


@pytest.fixture
def week(tenant_a, equipment_a, admin_a):
    with tenant_context(tenant_a):
        equipment_a.required_hours_per_day = D("8")
        equipment_a.operating_days_per_week = 5
        equipment_a.save()
        stops = [
            (at(2, 10), at(2, 14), "failure"),    # lundi : 4 h
            (at(3, 8), at(3, 9), "preventive"),   # mardi : 1 h planifiée
            (at(7, 9), at(7, 12), "failure"),     # samedi : jour non travaillé, ignoré
            (at(4, 20), at(5, 6), "failure"),     # mercredi 20 h → jeudi 6 h : 4 h + 6 h
        ]
        for start, end, origin in stops:
            Downtime.objects.create(equipment=equipment_a, started_at=start, ended_at=end, production_stopped=True, origin=origin)

        def order(kind, start, end, status="done", stopped=False):
            wo = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title=f"OT {kind}", kind=kind, priority=2)
            WorkOrder.objects.filter(pk=wo.pk).update(status=status, started_at=start, finished_at=end, production_stopped=stopped)

        order("corrective", at(2, 10), at(2, 13), stopped=True)              # 3 h
        order("corrective", at(4, 20), at(5, 5), status="validated", stopped=True)  # 9 h
        order("corrective", at(6, 9), at(6, 10))                             # 1 h, sans arrêt
        order("corrective", at(6, 11), at(6, 12), status="cancelled")        # annulé : pas une panne
        order("corrective", timezone.make_aware(datetime(2026, 2, 20, 9)), timezone.make_aware(datetime(2026, 2, 20, 10)))  # hors période
        order("preventive", at(3, 8), at(3, 9))
    return {"tenant": tenant_a, "equipment": equipment_a, "admin": admin_a}


@pytest.mark.django_db
def test_reliability_follows_documented_definitions(week):
    with tenant_context(week["tenant"]):
        rel = selectors.reliability(selectors.scope(), MONDAY, date(2026, 3, 8))
    assert rel.required == D("40")                       # 5 jours × 8 h
    assert rel.downtime_all == D("15") and rel.downtime_failure == D("14")
    assert rel.failures == 3 and rel.failures_stopped == 2
    assert round(rel.mtbf, 3) == D("8.667")              # (40 − 14) ÷ 3
    assert round(rel.mttr, 3) == D("4.333")              # (3 + 9 + 1) ÷ 3
    assert rel.mean_stop == D("7")                       # 14 h ÷ 2 pannes avec arrêt
    assert rel.availability == D("62.5") and rel.intrinsic == D("65")


@pytest.mark.django_db
def test_operating_days_and_daily_cap(week):
    equipment = week["equipment"]
    assert selectors.operating_days(equipment, MONDAY, date(2026, 3, 15)) == 10
    equipment.operating_days_per_week = 7
    assert selectors.required_hours(equipment, MONDAY, date(2026, 3, 8)) == D("56")
    long_stop = Downtime(started_at=at(2, 0), ended_at=at(4, 0), production_stopped=True)
    assert selectors.downtime_hours(long_stop, equipment, MONDAY, date(2026, 3, 8), timezone.now()) == D("16")  # 2 jours × 8 h


@pytest.mark.django_db
def test_page_rates_and_trend(week):
    with tenant_context(week["tenant"]):
        data = selectors.compute(start=MONDAY, end=date(2026, 3, 8))
        assert data["closed_count"] == 4 and data["corrective_rate"] == D("75")
        assert data["top_failures"][0]["equipment"] == week["equipment"]
        rows = selectors.trend(end=date(2026, 3, 31), months=3)
        assert [row["label"] for row in rows] == ["janv. 2026", "févr. 2026", "mars 2026"]
        assert rows[2]["failures"] == 3 and rows[1]["failures"] == 1


@pytest.mark.django_db
def test_screens_exports_and_rights(client, week, tenant_a):
    client.force_login(week["admin"])
    query = "?du=2026-03-02&au=2026-03-08"
    response = client.get(reverse("kpi:indicators") + query)
    assert response.status_code == 200 and response.context["rel"].failures == 3
    assert client.get(reverse("kpi:indicators") + query + f"&equipement_id={week['equipment'].pk}").status_code == 200
    assert "MTBF" in client.get(reverse("kpi:definitions")).content.decode()
    excel = client.get(reverse("kpi:export") + query)
    assert excel.status_code == 200 and excel["Content-Type"].startswith("application/vnd.openxml")
    pdf = client.get(reverse("kpi:pdf") + query)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    client.force_login(make_user(tenant_a, "technician", "tech_kpi"))
    assert client.get(reverse("kpi:indicators")).status_code == 403
    client.force_login(make_user(tenant_a, "storekeeper", "mag_kpi"))
    assert client.get(reverse("kpi:indicators")).status_code == 200


@pytest.mark.django_db
def test_isolation(client, week, admin_b):
    client.force_login(admin_b)
    response = client.get(reverse("kpi:indicators") + "?du=2026-03-02&au=2026-03-08")
    assert response.status_code == 200 and response.context["rel"].failures == 0 and response.context["d"]["equipment_count"] == 0
