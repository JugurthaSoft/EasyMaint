from django.db import transaction

from apps.core.models import Tenant
from apps.core.tenancy import tenant_context

from .capabilities import DEFAULT_ROLES
from .models import Role, User


def ensure_default_roles(tenant):
    """Crée les rôles prédéfinis manquants d'une entreprise (sans toucher aux rôles existants)."""
    from django.utils import translation

    # Noms enregistrés en français (langue de référence) ; ils s'affichent ensuite dans la langue de chacun.
    with tenant_context(tenant), translation.override("fr"):
        existing = set(Role.objects.values_list("code", flat=True))
        for code, (label, capabilities) in DEFAULT_ROLES.items():
            if code not in existing:
                Role.objects.create(code=code, name=str(label), capabilities=sorted(capabilities), is_system=True)


@transaction.atomic
def create_tenant(*, name, code, admin_username, admin_password, admin_email="", admin_first_name="", admin_last_name=""):
    """Crée une entreprise, ses rôles prédéfinis et son premier administrateur."""
    tenant = Tenant.objects.create(name=name, code=code)
    ensure_default_roles(tenant)
    with tenant_context(tenant):
        admin_role = Role.objects.get(code="admin")
    user = User(
        username=admin_username, email=admin_email, first_name=admin_first_name, last_name=admin_last_name,
        tenant=tenant, role=admin_role, job_title=str(admin_role),
    )
    user.set_password(admin_password)
    user.full_clean(exclude=["password"])
    user.save()
    return tenant, user
