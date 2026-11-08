"""Accueil : présentation par rôle, personnalisation par utilisateur, blocs limités aux droits."""
import pytest
from django.urls import reverse

from apps.core.tenancy import tenant_context
from apps.dashboard import blocks
from apps.dashboard.models import DashboardLayout
from conftest import make_user


@pytest.mark.django_db
def test_role_default_layout_respects_rights(client, admin_a, tenant_a, equipment_a):
    client.force_login(admin_a)
    response = client.get(reverse("dashboard:home"))
    keys = [block.key for block in response.context["blocks"]]
    assert keys[:3] == ["interventions", "reliability", "condition_alerts"] and "costs" in keys
    technician = make_user(tenant_a, "technician", "tech_dash")
    client.force_login(technician)
    keys = [block.key for block in client.get(reverse("dashboard:home")).context["blocks"]]
    assert "costs" not in keys and "reliability" not in keys and "broken" in keys
    assert "my_work" not in keys  # pas de fiche technicien reliée


@pytest.mark.django_db
def test_user_chooses_and_orders_blocks(client, tenant_a, equipment_a):
    manager = make_user(tenant_a, "maintenance_manager", "resp_dash")
    client.force_login(manager)
    assert client.get(reverse("dashboard:customize")).status_code == 200
    client.post(reverse("dashboard:customize"), {
        "order": ["stock", "broken", "costs", "fleet", "recent_changes"], "show": ["stock", "costs", "broken", "inconnu"],
    })
    with tenant_context(tenant_a):
        assert DashboardLayout.objects.get(user=manager).blocks == ["stock", "broken", "costs"]
    response = client.get(reverse("dashboard:home"))
    assert [block.key for block in response.context["blocks"]] == ["stock", "broken", "costs"]
    assert response.context["customized"]
    client.post(reverse("dashboard:customize"), {"reset": "1"})
    with tenant_context(tenant_a):
        assert not DashboardLayout.objects.filter(user=manager).exists()


@pytest.mark.django_db
def test_saved_layout_cannot_grant_unauthorized_blocks(client, tenant_a, equipment_a):
    technician = make_user(tenant_a, "technician", "tech_dash2")
    client.force_login(technician)
    client.post(reverse("dashboard:customize"), {"order": ["costs", "broken"], "show": ["costs", "broken"]})
    with tenant_context(tenant_a):
        assert DashboardLayout.objects.get(user=technician).blocks == ["broken"]
        DashboardLayout.objects.filter(user=technician).update(blocks=["costs", "broken"])  # même forcé en base
    assert [block.key for block in client.get(reverse("dashboard:home")).context["blocks"]] == ["broken"]


def test_every_role_default_is_in_registry():
    for keys in blocks.ROLE_DEFAULTS.values():
        assert set(keys) <= set(blocks.REGISTRY)
