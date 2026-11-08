"""
Sécurité transverse : blocage après échecs de connexion, en-têtes HTTP, et balayage de TOUTES les
adresses de l'application (aucune page accessible sans connexion, ni sans le droit requis).
"""
import re
import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.core.tenancy import tenant_context
from conftest import PASSWORD, make_user

LOGIN = reverse("accounts:login")


def login(client, username, password):
    return client.post(LOGIN, {"username": username, "password": password})


@pytest.mark.django_db
@override_settings(EASYMAINT_LOGIN_MAX_FAILURES=3, EASYMAINT_LOGIN_LOCK_MINUTES=15)
def test_login_is_locked_after_repeated_failures(client, admin_a):
    for _attempt in range(3):
        assert login(client, "admin_a", "mauvais").status_code == 200
    response = login(client, "ADMIN_A", PASSWORD)  # même identifiant, casse différente, bon mot de passe
    assert response.status_code == 200 and "Trop de tentatives" in response.content.decode()
    assert "_auth_user_id" not in client.session
    # Le blocage se lève seul : on vieillit les échecs au-delà de la fenêtre.
    AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).update(at=timezone.now() - timedelta(minutes=16))
    assert login(client, "admin_a", PASSWORD).status_code == 302


@pytest.mark.django_db
@override_settings(EASYMAINT_LOGIN_MAX_FAILURES=3)
def test_success_resets_counter_and_other_users_are_not_locked(client, tenant_a, admin_a):
    make_user(tenant_a, "technician", "karim")
    login(client, "admin_a", "mauvais")
    login(client, "admin_a", "mauvais")
    assert login(client, "admin_a", PASSWORD).status_code == 302
    client.logout()
    login(client, "admin_a", "mauvais")
    login(client, "admin_a", "mauvais")
    assert login(client, "admin_a", PASSWORD).status_code == 302  # compteur remis à zéro par la connexion réussie
    client.logout()
    for _attempt in range(3):
        login(client, "admin_a", "mauvais")
    assert login(client, "karim", PASSWORD).status_code == 302  # un autre identifiant n'est pas bloqué


@pytest.mark.django_db
@override_settings(EASYMAINT_LOGIN_MAX_FAILURES=2)
def test_ip_is_locked_after_many_failures_on_various_usernames(client, admin_a):
    for index in range(8):  # 4 × 2 échecs depuis la même adresse
        login(client, f"inconnu{index}", "x")
    response = login(client, "admin_a", PASSWORD)
    assert response.status_code == 200 and "Trop de tentatives" in response.content.decode()


@pytest.mark.django_db
def test_forwarded_header_is_ignored_without_trusted_proxy(client, admin_a):
    client.post(LOGIN, {"username": "admin_a", "password": "x"}, HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED).ip_address == "127.0.0.1"
    with override_settings(EASYMAINT_BEHIND_PROXY=True):
        client.post(LOGIN, {"username": "admin_a", "password": "x"}, HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.9")
    assert AuditLog.objects.filter(ip_address="10.0.0.9").exists()  # adresse ajoutée par le proxy


@pytest.mark.django_db
def test_security_headers(client, admin_a):
    client.force_login(admin_a)
    response = client.get(reverse("dashboard:home"))
    csp = response["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    assert response["X-Frame-Options"] == "DENY" and response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin" and "Permissions-Policy" in response
    assert "<script>" not in response.content.decode()  # aucun script en ligne (bloqué par la CSP)


# --- Balayage de toutes les adresses ------------------------------------------------------------

SAMPLES = {"int": "1", "str": "x", "slug": "x", "uuid": str(uuid.uuid4()), "path": "x"}
PUBLIC = {"accounts:login", "core:about"}
# Pages ouvertes à tout utilisateur connecté, même sans aucun droit (leur contenu est filtré).
# « api-root » : sommaire de l'API (liste des adresses, aucune donnée) ; chaque adresse vérifie ensuite les droits.
ANY_USER = {"dashboard:home", "dashboard:customize", "accounts:profile", "notifications:list", "core:search", "api-root"}


def _route(pattern):
    if hasattr(pattern, "_route"):
        if "format" in pattern._route:  # variantes « .json » des adresses de l'API : même vue
            return None
        return re.sub(r"<(?:(\w+):)?\w+>", lambda m: SAMPLES.get(m.group(1) or "str", "x"), pattern._route)
    regex = pattern._regex
    if "format" in regex:
        return None
    regex = regex.lstrip("^").rstrip("$").replace("\\Z", "")
    regex = re.sub(r"\(\?P<\w+>[^)]*\)", "1", regex)
    return None if re.search(r"[\\(\[\]*+?]", regex) else regex


def all_urls(resolver=None, prefix="", namespace=""):
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        part = _route(entry.pattern)
        if part is None:
            continue
        if isinstance(entry, URLResolver):
            if entry.namespace == "admin" or "static" in part or "media" in part:
                continue
            ns = f"{namespace}:{entry.namespace}".strip(":") if entry.namespace else namespace
            yield from all_urls(entry, prefix + part, ns)
        elif isinstance(entry, URLPattern):
            name = (f"{namespace}:{entry.name}" if namespace else entry.name) if entry.name else ""
            yield name, "/" + prefix + part


def test_the_sweep_covers_the_whole_application():
    names = {name for name, _url in all_urls()}
    assert len(names) > 150
    for expected in ("workorders:wo_list", "inventory:item_list", "finance:costs", "kpi:indicators", "imports:home",
                     "notifications:list", "core:backups", "condition:overview"):
        assert expected in names


@pytest.mark.django_db
def test_no_page_is_reachable_anonymously(client, tenant_a):
    for name, url in all_urls():
        if name in PUBLIC:
            continue
        response = client.get(url)
        assert response.status_code in (302, 401, 403, 404, 405), f"{name} {url} → {response.status_code}"
        if response.status_code == 302:
            assert response["Location"].startswith(LOGIN), f"{name} {url} → {response['Location']}"


@pytest.mark.django_db
def test_no_page_is_reachable_without_the_required_capability(client, tenant_a, equipment_a):
    with tenant_context(tenant_a):
        role = Role.objects.create(code="sans-droit", name="Sans droit", capabilities=[])
    user = make_user(tenant_a, "technician", "sans_droit")
    user.role = role
    user.save()
    client.force_login(user)
    for name, url in all_urls():
        if name in PUBLIC or name == "accounts:logout":
            continue
        response = client.get(url)
        if name in ANY_USER:
            assert response.status_code == 200, f"{name} {url} → {response.status_code}"
        else:
            assert response.status_code in (302, 401, 403, 404, 405), f"{name} {url} → {response.status_code}"
            if response.status_code == 302:
                assert not response["Location"].startswith(LOGIN), f"{name} {url}"


@pytest.mark.django_db
def test_backups_page(client, admin_a, tmp_path, settings):
    settings.EASYMAINT_BACKUP_DIR = tmp_path
    client.force_login(admin_a)
    page = client.get(reverse("core:backups"))
    assert page.status_code == 200 and page.context["stale"]
    (tmp_path / "easymaint-db-20261101-0100.dump").write_bytes(b"x" * 10)
    (tmp_path / "easymaint-media-20261101-0100.tar.gz").write_bytes(b"x")
    (tmp_path / "easymaint-db-20261102-0100.dump.part").write_bytes(b"x")
    page = client.get(reverse("core:backups"))
    assert sorted(f["name"] for f in page.context["files"]) == ["easymaint-db-20261101-0100.dump", "easymaint-media-20261101-0100.tar.gz"]
    assert not page.context["stale"]  # fichiers écrits à l'instant
    settings.DEPLOYMENT_MODE = "saas"
    assert client.get(reverse("core:backups")).status_code == 404


@pytest.mark.django_db
def test_migrations_match_the_models():
    """Toute modification de modèle est livrée avec sa migration."""
    from io import StringIO

    from django.core.management import call_command

    output = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=output, stderr=output)
    except SystemExit:
        pytest.fail("Migrations manquantes :\n" + output.getvalue())


@pytest.mark.django_db
def test_about_page_shows_version_licence_and_source(client, admin_a, settings):
    settings.EASYMAINT_SOURCE_URL = "https://exemple.org/easymaint"
    page = client.get(reverse("core:about")).content.decode()  # sans connexion
    assert settings.EASYMAINT_VERSION in page and "AGPL" in page and "https://exemple.org/easymaint" in page
    assert reverse("core:about") in client.get(LOGIN).content.decode()
    client.force_login(admin_a)
    assert "AGPL" in client.get(reverse("core:about")).content.decode()
    assert settings.EASYMAINT_VERSION in client.get(reverse("dashboard:home")).content.decode()


@pytest.mark.django_db
def test_tls_check_only_allows_active_tenants(client, tenant_a, settings):
    url = reverse("tls_check")
    assert client.get(url, {"domain": "ent-a.easymaint.test"}).status_code == 404  # installation locale : fermé
    settings.DEPLOYMENT_MODE = "saas"
    settings.SAAS_BASE_DOMAIN = "easymaint.test"
    assert client.get(url, {"domain": "ent-a.easymaint.test"}).status_code == 200
    assert client.get(url, {"domain": "easymaint.test"}).status_code == 200
    for refused in ("inconnue.easymaint.test", "x.ent-a.easymaint.test", "ent-a.autre.test", ""):
        assert client.get(url, {"domain": refused}).status_code == 404, refused
    tenant_a.is_active = False
    tenant_a.save()
    assert client.get(url, {"domain": "ent-a.easymaint.test"}).status_code == 404
