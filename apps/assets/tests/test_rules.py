"""Règles métier du patrimoine : arborescences sans boucle, compteurs cohérents."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.assets.models import Equipment, Location, Meter
from apps.assets.selectors import descendant_location_ids, location_paths, location_tree
from apps.assets.services import record_reading
from apps.core.tenancy import tenant_context
from conftest import make_equipment


@pytest.mark.django_db
def test_location_cannot_be_moved_under_its_own_descendant(tenant_a):
    with tenant_context(tenant_a):
        site = Location.objects.create(code="S", name="Usine", kind="site")
        workshop = Location.objects.create(code="W", name="Unité", kind="workshop", parent=site)
        site.parent = workshop
        with pytest.raises(ValidationError):
            site.full_clean()


@pytest.mark.django_db
def test_location_paths_and_descendants(tenant_a):
    with tenant_context(tenant_a):
        site = Location.objects.create(code="S", name="Usine", kind="site")
        workshop = Location.objects.create(code="W", name="Unité", kind="workshop", parent=site)
        line = Location.objects.create(code="L", name="Ligne 1", kind="line", parent=workshop)
        assert location_paths()[line.pk] == "Usine › Unité › Ligne 1"
        assert set(descendant_location_ids(site.pk)) == {site.pk, workshop.pk, line.pk}
        tree = location_tree()
        assert tree[0]["location"] == site and tree[0]["children"][0]["children"][0]["location"] == line


@pytest.mark.django_db
def test_equipment_parent_loop_is_rejected(tenant_a):
    parent = make_equipment(tenant_a, "P1")
    child = make_equipment(tenant_a, "C1", parent=parent)
    with tenant_context(tenant_a):
        parent.parent = child
        with pytest.raises(ValidationError):
            parent.full_clean()


@pytest.mark.django_db
def test_equipment_code_is_unique_per_tenant_only(tenant_a, tenant_b):
    make_equipment(tenant_a, "SAME")
    make_equipment(tenant_b, "SAME")  # autorisé : autre entreprise
    with tenant_context(tenant_a):
        duplicate = Equipment(code="SAME", designation="x", family_id=Equipment.objects.first().family_id,
                              location_id=Equipment.objects.first().location_id)
        with pytest.raises(ValidationError):
            duplicate.full_clean()


@pytest.mark.django_db
def test_cumulative_meter_never_decreases(tenant_a, equipment_a):
    now = timezone.now()
    with tenant_context(tenant_a):
        meter = Meter.objects.create(equipment=equipment_a, name="Heures", kind="hours")
        record_reading(meter, 1000, reading_at=now - timedelta(days=10))
        record_reading(meter, 1100, reading_at=now - timedelta(days=5))
        with pytest.raises(ValidationError):
            record_reading(meter, 1050, reading_at=now)
        # Relevé rétroactif cohérent, entre deux relevés existants : accepté
        record_reading(meter, 1040, reading_at=now - timedelta(days=7))
        # Relevé rétroactif supérieur au relevé suivant : refusé
        with pytest.raises(ValidationError):
            record_reading(meter, 1200, reading_at=now - timedelta(days=6))
        meter.refresh_from_db()
        assert meter.current_value == Decimal("1100")


@pytest.mark.django_db
def test_meter_value_follows_latest_reading_only(tenant_a, equipment_a):
    now = timezone.now()
    with tenant_context(tenant_a):
        meter = Meter.objects.create(equipment=equipment_a, name="Cycles", kind="cycles", is_cumulative=False)
        record_reading(meter, 50, reading_at=now - timedelta(days=1))
        record_reading(meter, 20, reading_at=now - timedelta(days=3))  # plus ancien : ne change pas la valeur actuelle
        meter.refresh_from_db()
        assert meter.current_value == Decimal("50")
        assert meter.unit == "cycles"


@pytest.mark.django_db
def test_future_or_negative_readings_are_refused(tenant_a, equipment_a):
    with tenant_context(tenant_a):
        meter = Meter.objects.create(equipment=equipment_a, name="Heures", kind="hours")
        with pytest.raises(ValidationError):
            record_reading(meter, 10, reading_at=timezone.now() + timedelta(days=1))
        with pytest.raises(ValidationError):
            record_reading(meter, -1)
