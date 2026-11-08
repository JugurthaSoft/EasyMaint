"""Fixtures communes des tests EasyMaint."""
import pytest

from apps.accounts.models import Role, User
from apps.accounts.services import create_tenant
from apps.assets.models import Equipment, EquipmentFamily, Location
from apps.core.tenancy import tenant_context

PASSWORD = "Mot-de-passe-Tests-2026"


@pytest.fixture
def tenant_a(db):
    tenant, _admin = create_tenant(name="Entreprise A", code="ent-a", admin_username="admin_a", admin_password=PASSWORD)
    return tenant


@pytest.fixture
def tenant_b(db):
    tenant, _admin = create_tenant(name="Entreprise B", code="ent-b", admin_username="admin_b", admin_password=PASSWORD)
    return tenant


def make_user(tenant, role_code, username):
    with tenant_context(tenant):
        role = Role.objects.get(code=role_code)
    user = User(username=username, first_name=username.title(), last_name="Test", tenant=tenant, role=role)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def admin_a(tenant_a):
    return User.objects.get(username="admin_a")


@pytest.fixture
def admin_b(tenant_b):
    return User.objects.get(username="admin_b")


@pytest.fixture
def technician_a(tenant_a):
    return make_user(tenant_a, "technician", "tech_a")


def make_equipment(tenant, code="EQ-01", **extra):
    """Crée une localisation, une famille et un équipement dans l'entreprise donnée."""
    with tenant_context(tenant):
        location, _ = Location.objects.get_or_create(code="SITE", defaults={"name": "Usine", "kind": "site"})
        family, _ = EquipmentFamily.objects.get_or_create(code="FAM", defaults={"name": "Presses"})
        return Equipment.objects.create(code=code, designation=f"Machine {code}", family=family, location=location, **extra)


@pytest.fixture
def equipment_a(tenant_a):
    return make_equipment(tenant_a, "PRS-A1")


@pytest.fixture
def equipment_b(tenant_b):
    return make_equipment(tenant_b, "PRS-B1")
