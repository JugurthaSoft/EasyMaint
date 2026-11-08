"""Budgets de démonstration : un budget annuel par unité, à peine au-dessus du rythme de dépense observé."""
from datetime import date
from decimal import Decimal

from django.utils import timezone

from . import selectors
from .models import MONTH_FIELDS, Budget


def load(tenant, *, author=None):
    if Budget.objects.exists():
        return 0
    today = timezone.localdate()
    year = today.year
    records = selectors.cost_records(date(year - 1, today.month, 1), today)
    months_seen = max(1, len({(r.day.year, r.day.month) for r in records}))
    created = 0
    for unit in selectors.units():
        spent = sum((r.total for r in records if r.unit_id == unit.pk), Decimal("0"))
        monthly = max(Decimal("800"), (spent / months_seen * Decimal("1.10")).quantize(Decimal("100")))
        values = {name: monthly for name in MONTH_FIELDS}
        # Arrêt technique d'été : budget d'août doublé.
        values["month_08"] = monthly * 2
        Budget.objects.create(year=year, unit=unit, created_by=author, notes="Budget de démonstration", **values)
        created += 1
    return created
