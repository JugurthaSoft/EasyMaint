import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.core.formatting import NARROW_NBSP, format_money, format_number, smart_number
from apps.core.models import AuditLog
from apps.core.services import next_document_number
from apps.core.tenancy import tenant_context


@pytest.mark.django_db
def test_document_numbers_are_sequential_and_per_tenant(tenant_a, tenant_b):
    with tenant_context(tenant_a):
        assert next_document_number("OT", year=2026) == "OT-2026-000001"
        assert next_document_number("OT", year=2026) == "OT-2026-000002"
        assert next_document_number("DI", year=2026) == "DI-2026-000001"
        assert next_document_number("OT", year=2027) == "OT-2027-000001"
    with tenant_context(tenant_b):
        assert next_document_number("OT", year=2026) == "OT-2026-000001"


@pytest.mark.django_db
def test_document_number_requires_a_tenant():
    with pytest.raises(RuntimeError):
        next_document_number("OT")


def test_unknown_document_type_is_refused():
    with pytest.raises(ValueError):
        next_document_number("XX")


def test_money_uses_three_decimals_and_french_separators():
    assert format_money(1234567.8915) == f"1{NARROW_NBSP}234{NARROW_NBSP}567,892 TND"
    assert format_money(0) == "0,000 TND"
    assert format_money(-42.5, "EUR", 2) == "-42,50 EUR"


def test_number_formatting():
    assert format_number(18432) == f"18{NARROW_NBSP}432"
    assert smart_number("18432.00") == f"18{NARROW_NBSP}432"
    assert smart_number("2.50") == "2,5"
    assert format_number(None) == ""


@pytest.mark.django_db
def test_audit_log_cannot_be_modified_or_deleted(tenant_a):
    entry = AuditLog.objects.create(tenant=tenant_a, username="x", action=AuditLog.Action.LOGIN)
    entry.username = "y"
    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        entry.delete()


@pytest.mark.django_db
def test_migrations_match_the_models():
    """Échoue si un modèle a changé sans migration correspondante."""
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
