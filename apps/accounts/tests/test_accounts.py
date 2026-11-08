import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.capabilities import ALL_CAPABILITIES, DEFAULT_ROLES
from apps.accounts.models import Role, User
from apps.core.models import AuditLog, Tenant
from apps.core.tenancy import tenant_context
from conftest import PASSWORD, make_user


@pytest.mark.django_db
def test_create_tenant_seeds_all_default_roles(tenant_a, admin_a):
    with tenant_context(tenant_a):
        assert set(Role.objects.values_list("code", flat=True)) == set(DEFAULT_ROLES)
    assert admin_a.role.code == "admin"
    assert admin_a.has_capability("settings.manage")


@pytest.mark.django_db
def test_role_capabilities(technician_a, tenant_a):
    assert technician_a.has_capability("workorders.execute")
    assert technician_a.has_capability("meters.record")
    assert not technician_a.has_capability("assets.manage")
    assert not technician_a.has_capability("settings.manage")
    manager = make_user(tenant_a, "maintenance_manager", "manager_a")
    assert manager.has_capability("workorders.validate")
    assert not manager.has_capability("settings.manage")


@pytest.mark.django_db
def test_inactive_user_or_user_without_tenant_has_no_capability(technician_a):
    technician_a.is_active = False
    assert not technician_a.has_capability("assets.view")
    platform = User.objects.create_superuser("platform", "p@example.com", PASSWORD)
    assert not platform.has_capability("assets.view")


@pytest.mark.django_db
def test_role_drops_unknown_capabilities(tenant_a):
    with tenant_context(tenant_a):
        role = Role.objects.create(code="custom", name="Perso", capabilities=["assets.view", "inexistant"])
    assert role.capabilities == ["assets.view"]
    assert set(DEFAULT_ROLES["admin"][1]) == set(ALL_CAPABILITIES)


@pytest.mark.django_db
def test_login_and_failed_login_are_logged(client, admin_a):
    client.post(reverse("accounts:login"), {"username": "admin_a", "password": "faux"})
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, username="admin_a").exists()
    response = client.post(reverse("accounts:login"), {"username": "admin_a", "password": PASSWORD})
    assert response.status_code == 302
    assert AuditLog.objects.filter(action=AuditLog.Action.LOGIN, user=admin_a, tenant=admin_a.tenant).exists()


@pytest.mark.django_db
def test_inactive_tenant_cannot_log_in(client, admin_a):
    Tenant.objects.filter(pk=admin_a.tenant_id).update(is_active=False)
    response = client.post(reverse("accounts:login"), {"username": "admin_a", "password": PASSWORD})
    assert response.status_code == 200  # formulaire réaffiché avec l'erreur
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_user_list_shows_only_own_tenant(client, admin_a, admin_b):
    client.force_login(admin_a)
    response = client.get(reverse("accounts:user_list"))
    assert response.status_code == 200
    usernames = [u.username for u in response.context["users"]]
    assert "admin_a" in usernames and "admin_b" not in usernames


@pytest.mark.django_db
def test_cannot_edit_a_user_from_another_tenant(client, admin_a, admin_b):
    client.force_login(admin_a)
    assert client.get(reverse("accounts:user_update", args=[admin_b.pk])).status_code == 404


@pytest.mark.django_db
def test_technician_cannot_manage_users(client, technician_a):
    client.force_login(technician_a)
    assert client.get(reverse("accounts:user_list")).status_code == 403
    assert client.get(reverse("accounts:role_list")).status_code == 403


@pytest.mark.django_db
def test_admin_creates_a_user_in_own_tenant(client, admin_a, tenant_a):
    client.force_login(admin_a)
    with tenant_context(tenant_a):
        role = Role.objects.get(code="technician")
    response = client.post(reverse("accounts:user_create"), {
        "username": "nouveau", "first_name": "Nadia", "last_name": "Ben Ali", "role": role.pk,
        "password1": PASSWORD, "password2": PASSWORD, "job_title": "", "email": "", "phone": "",
    })
    assert response.status_code == 302
    created = User.objects.get(username="nouveau")
    assert created.tenant_id == tenant_a.pk and created.role == role
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(created.pk)).exists()


@pytest.mark.django_db
def test_admin_cannot_assign_a_role_from_another_tenant(client, admin_a, tenant_b):
    client.force_login(admin_a)
    with tenant_context(tenant_b):
        foreign_role = Role.objects.get(code="technician")
    response = client.post(reverse("accounts:user_create"), {
        "username": "intrus", "first_name": "X", "last_name": "Y", "role": foreign_role.pk,
        "password1": PASSWORD, "password2": PASSWORD,
    })
    assert response.status_code == 200
    assert "role" in response.context["form"].errors


@pytest.mark.django_db
def test_admin_cannot_deactivate_himself(client, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("accounts:user_update", args=[admin_a.pk]), {
        "first_name": "Admin", "last_name": "A", "role": admin_a.role_id, "is_active": "",
    })
    assert response.status_code == 200
    admin_a.refresh_from_db()
    assert admin_a.is_active


@pytest.mark.django_db
def test_admin_role_keeps_user_management(client, admin_a):
    client.force_login(admin_a)
    response = client.post(reverse("accounts:role_update", args=[admin_a.role_id]), {
        "name": "Administrateur", "capabilities": ["assets.view"],
    })
    assert response.status_code == 200
    admin_a.role.refresh_from_db()
    assert "settings.manage" in admin_a.role.capabilities


@pytest.mark.django_db
def test_create_tenant_command():
    call_command("create_tenant", name="Usine Test", code="usine-test", admin="chef", password=PASSWORD)
    user = User.objects.get(username="chef")
    assert user.tenant.code == "usine-test" and user.has_capability("settings.manage")
