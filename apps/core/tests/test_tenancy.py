"""La séparation stricte des données entre entreprises est la règle la plus importante du socle."""
import pytest
from django.core.exceptions import ValidationError

from apps.assets.models import Location
from apps.core.tenancy import get_current_tenant, tenant_context


@pytest.mark.django_db
def test_without_current_tenant_the_manager_returns_nothing(tenant_a):
    with tenant_context(tenant_a):
        Location.objects.create(code="S1", name="Usine A", kind="site")
    assert get_current_tenant() is None
    assert Location.objects.count() == 0
    assert Location.all_tenants.count() == 1


@pytest.mark.django_db
def test_each_tenant_only_sees_its_own_rows(tenant_a, tenant_b):
    with tenant_context(tenant_a):
        Location.objects.create(code="S1", name="Usine A", kind="site")
    with tenant_context(tenant_b):
        Location.objects.create(code="S1", name="Usine B", kind="site")  # même code autorisé dans une autre entreprise
        assert list(Location.objects.values_list("name", flat=True)) == ["Usine B"]
    with tenant_context(tenant_a):
        assert list(Location.objects.values_list("name", flat=True)) == ["Usine A"]


@pytest.mark.django_db
def test_save_assigns_the_current_tenant(tenant_a):
    with tenant_context(tenant_a):
        location = Location.objects.create(code="S1", name="Usine", kind="site")
    assert location.tenant_id == tenant_a.pk


@pytest.mark.django_db
def test_save_without_tenant_is_refused(tenant_a):
    with pytest.raises(ValidationError):
        Location(code="S1", name="Usine", kind="site").save()


@pytest.mark.django_db
def test_parent_from_another_tenant_is_rejected(tenant_a, tenant_b):
    with tenant_context(tenant_b):
        foreign = Location.objects.create(code="B1", name="Usine B", kind="site")
    with tenant_context(tenant_a):
        location = Location(code="A1", name="Unité", kind="workshop", parent=foreign)
        with pytest.raises(ValidationError) as error:
            location.full_clean()
    assert "parent" in error.value.message_dict


def test_tenant_context_is_restored_after_the_block():
    sentinel = object()
    with tenant_context(sentinel):
        assert get_current_tenant() is sentinel
    assert get_current_tenant() is None
