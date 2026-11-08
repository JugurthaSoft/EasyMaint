"""
Langue de l'installation (français ou anglais) : pages, formats, documents, imports bilingues,
démonstration anglaise, et contrôle que TOUS les textes du logiciel ont leur traduction anglaise.
"""
import io
import os
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import translation
from openpyxl import Workbook, load_workbook

from apps.accounts.models import Role, User
from apps.core.formatting import format_money, month_abbr
from apps.core.tenancy import tenant_context

PO_FILE = Path(settings.BASE_DIR) / "locale" / "en" / "LC_MESSAGES" / "django.po"
PLACEHOLDER = re.compile(r"%\([a-z_]+\)[sd]|%%")


def read_po(path):
    """{(contexte, msgid): [msgstr…]} d'un fichier .po (lecture minimale, suffisante pour les contrôles)."""
    entries, current, key = {}, {}, None

    def flush():
        if "msgid" in current and current["msgid"]:
            entries[(current.get("msgctxt", ""), current["msgid"])] = current.get("msgstr", [])
        current.clear()

    def unquote(text):
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
        return re.sub(r"\\(.)", lambda m: escapes.get(m.group(1), m.group(1)), text[1:-1])

    for line in Path(path).read_text(encoding="utf-8").splitlines() + [""]:
        if not line.strip():
            flush()
            key = None
            continue
        if line.startswith("#"):
            continue
        match = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d\])?) (".*")$', line)
        if match:
            key = match.group(1)
            value = unquote(match.group(2))
            if key.startswith("msgstr"):
                current.setdefault("msgstr", []).append(value)
            else:
                current[key] = value
        elif line.startswith('"') and key:
            value = unquote(line)
            if key.startswith("msgstr"):
                current["msgstr"][-1] += value
            else:
                current[key] += value
    return entries


def test_english_catalog_is_complete_and_consistent(tmp_path, monkeypatch):
    """Extrait les textes comme « makemessages » et vérifie qu'aucun n'est sans traduction anglaise."""
    english = read_po(PO_FILE)
    assert len(english) > 2000
    for (ctx, msgid), forms in english.items():
        assert all(forms), f"traduction vide : {msgid!r}"
        for form in forms:
            assert sorted(set(PLACEHOLDER.findall(msgid))) == sorted(set(PLACEHOLDER.findall(form))), msgid
    # Arborescence de travail : liens vers le code, catalogue produit dans un dossier temporaire.
    for name in ("apps", "templates"):
        os.symlink(Path(settings.BASE_DIR) / name, tmp_path / name)
    (tmp_path / "locale").mkdir()
    monkeypatch.chdir(tmp_path)
    with override_settings(LOCALE_PATHS=[str(tmp_path / "locale")]):
        call_command("makemessages", locale=["en"], symlinks=True, verbosity=0, no_location=True)
    extracted = read_po(tmp_path / "locale" / "en" / "LC_MESSAGES" / "django.po")
    missing = sorted(msgid for key, msgid in ((k, k[1]) for k in extracted) if key not in english)
    assert not missing, f"{len(missing)} texte(s) sans traduction anglaise : {missing[:20]}"


@pytest.mark.django_db
def test_installation_language(client, admin_a):
    client.force_login(admin_a)
    page = client.get(reverse("dashboard:home")).content.decode()
    assert 'lang="fr"' in page and "Ordres de travail" in page
    with override_settings(LANGUAGE_CODE="en"):
        page = client.get(reverse("dashboard:home")).content.decode()
        assert 'lang="en"' in page and "Work orders" in page and "Ordres de travail" not in page
        client.logout()
        assert "Log in" in client.get(reverse("accounts:login")).content.decode()
    # Pas de choix par utilisateur : la langue est celle de l'installation pour tout le monde.
    client.force_login(admin_a)
    profile = client.get(reverse("accounts:profile")).content.decode()
    assert "English" not in profile


@pytest.mark.django_db
def test_formats_roles_and_documents_in_english(client, tenant_a, admin_a, equipment_a):
    from apps.workorders import services as wo_services

    with translation.override("en"):
        assert format_money("1234.5", "TND", 3) == "1,234.500\xa0TND" and month_abbr(3) == "Mar"
        with tenant_context(tenant_a):
            assert str(Role.objects.get(code="technician")) == "Technician"
    with translation.override("fr"):
        assert format_money("1234.5", "TND", 3) == "1\u202f234,500\xa0TND" and month_abbr(3) == "mars"
        with tenant_context(tenant_a):
            assert str(Role.objects.get(code="technician")) == "Technicien"
    with tenant_context(tenant_a):
        wo = wo_services.create_work_order(user=admin_a, equipment=equipment_a, title="Belt", kind="corrective", priority=2)
    client.force_login(admin_a)
    with override_settings(LANGUAGE_CODE="en"):
        assert client.get(reverse("workorders:wo_pdf", args=[wo.pk])).content.startswith(b"%PDF")
        sheet = load_workbook(io.BytesIO(client.get(reverse("assets:equipment_export")).content)).active
        headers = [cell.value for cell in sheet[1]]
        assert "Description" in headers and "Désignation" not in headers
        template = load_workbook(io.BytesIO(client.get(reverse("imports:template", args=["equipements"])).content))
        assert "Data" in template.sheetnames and template["Data"]["B1"].value == "Description"


@pytest.mark.django_db
def test_imports_recognise_english_headers(client, tenant_a, admin_a, equipment_a):
    from apps.assets.models import Equipment

    workbook = Workbook()
    workbook.active.append(["Code", "Description", "Family", "Location", "Criticality"])
    workbook.active.append(["CMP-90", "Screw compressor", "FAM", "SITE", "A"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    from django.core.files.uploadedfile import SimpleUploadedFile

    client.force_login(admin_a)  # interface en français : les titres anglais sont reconnus quand même
    response = client.post(reverse("imports:home"), {"kind": "equipements", "file": SimpleUploadedFile("eq.xlsx", buffer.getvalue())})
    imp_pk = int(response["Location"].rstrip("/").split("/")[-1])
    client.post(reverse("imports:confirm", args=[imp_pk]))
    with tenant_context(tenant_a):
        assert Equipment.objects.get(code="CMP-90").criticality == "A"


@pytest.mark.django_db
def test_english_demo(db):
    call_command("load_demo", password="Demo-EasyMaint-2026!", lang="en", code="demo-en")
    from apps.assets.models import Equipment, Location
    from apps.core.models import Tenant

    tenant = Tenant.objects.get(code="demo-en")
    assert tenant.name == "Demo Company"
    manager = User.objects.get(username="s.bensalah.en")
    assert manager.tenant == tenant and manager.job_title == "Maintenance manager"
    with tenant_context(tenant):
        assert Location.objects.filter(name="Injection unit").exists()
        assert Equipment.objects.filter(designation="350 t injection moulding machine").exists()
        assert not Equipment.objects.filter(designation__startswith="Presse").exists()
