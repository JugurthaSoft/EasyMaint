"""Lectures du magasin : listes annotées (physique, réservé, disponible, valeur), alertes, recherche."""
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.search import SearchResult

from .models import Item, StockLevel, StockMovement, WorkOrderPart

ZERO = Decimal("0")
QTY = DecimalField(max_digits=14, decimal_places=3)
MONEY = DecimalField(max_digits=18, decimal_places=3)


def _physical(warehouse=None):
    levels = StockLevel.objects.filter(item=OuterRef("pk"))
    if warehouse is not None:
        levels = levels.filter(warehouse=warehouse)
    return Coalesce(Subquery(levels.values("item").annotate(q=Sum("quantity")).values("q")[:1], output_field=QTY),
                    Value(ZERO), output_field=QTY)


def _reserved(warehouse=None):
    lines = WorkOrderPart.objects.filter(item=OuterRef("pk"), status__in=WorkOrderPart.OPEN_STATUSES)
    if warehouse is not None:
        lines = lines.filter(warehouse=warehouse)
    remaining = ExpressionWrapper(F("quantity") - F("issued"), output_field=QTY)
    return Coalesce(Subquery(lines.values("item").annotate(q=Sum(remaining)).values("q")[:1], output_field=QTY),
                    Value(ZERO), output_field=QTY)


def items_with_stock(queryset=None, warehouse=None):
    queryset = Item.objects.all() if queryset is None else queryset
    return queryset.select_related("family").annotate(
        physical=_physical(warehouse), reserved=_reserved(warehouse),
    ).annotate(
        available=ExpressionWrapper(F("physical") - F("reserved"), output_field=QTY),
        stock_value=ExpressionWrapper(F("physical") * F("average_cost"), output_field=MONEY),
    ).annotate(
        below_min=Case(When(Q(min_stock__gt=0) & Q(available__lt=F("min_stock")), then=Value(True)), default=Value(False)),
    )


STATES = [
    ("sous-mini", gettext_lazy("Sous le minimum")),
    ("rupture", gettext_lazy("En rupture")),
    ("critiques", gettext_lazy("Pièces critiques")),
    ("inactifs", gettext_lazy("Désactivés")),
]


def filter_items(params, warehouse=None):
    items = items_with_stock(warehouse=warehouse)
    state = params.get("etat", "")
    items = items.filter(is_active=False) if state == "inactifs" else items.filter(is_active=True)
    query = (params.get("q") or "").strip()
    if query:
        items = items.filter(
            Q(reference__icontains=query) | Q(designation__icontains=query) | Q(manufacturer_reference__icontains=query)
            | Q(brand__icontains=query) | Q(suppliers__supplier_reference__icontains=query)
        ).distinct()
    family = params.get("famille")
    if family and str(family).isdigit():
        items = items.filter(family_id=int(family))
    if state == "sous-mini":
        items = items.filter(below_min=True)
    elif state == "rupture":
        items = items.filter(available__lte=0)
    elif state == "critiques":
        items = items.filter(is_critical=True)
    return items.order_by("reference")


def below_minimum(limit=None):
    items = items_with_stock(Item.objects.filter(is_active=True)).filter(below_min=True).order_by("-is_critical", "reference")
    return items if limit is None else items[:limit]


def stock_value():
    return StockLevel.objects.aggregate(
        v=Sum(ExpressionWrapper(F("quantity") * F("item__average_cost"), output_field=MONEY)),
    )["v"] or ZERO


def overview():
    below = list(below_minimum())
    return {
        "below_count": len(below),
        "below": below[:6],
        "critical_below": sum(1 for item in below if item.is_critical),
        "value": stock_value(),
        "open_requests": WorkOrderPart.objects.filter(status__in=WorkOrderPart.OPEN_STATUSES).count(),
    }


def open_requests():
    return (WorkOrderPart.objects.filter(status__in=WorkOrderPart.OPEN_STATUSES)
            .select_related("item", "warehouse", "work_order", "work_order__equipment", "created_by")
            .order_by("work_order__priority", "pk"))


def filter_movements(params):
    movements = StockMovement.objects.select_related("item", "warehouse", "work_order", "created_by", "equipment", "supplier")
    query = (params.get("q") or "").strip()
    if query:
        movements = movements.filter(
            Q(item__reference__icontains=query) | Q(item__designation__icontains=query) | Q(number__icontains=query)
            | Q(document__icontains=query) | Q(work_order__number__icontains=query)
        )
    kind = params.get("type")
    if kind in dict(StockMovement.Kind.choices):
        movements = movements.filter(kind=kind)
    warehouse = params.get("magasin")
    if warehouse and str(warehouse).isdigit():
        movements = movements.filter(warehouse_id=int(warehouse))
    item = params.get("article")
    if item and str(item).isdigit():
        movements = movements.filter(item_id=int(item))
    for name, lookup in (("du", "moved_at__date__gte"), ("au", "moved_at__date__lte")):
        value = params.get(name)
        if value:
            from django.utils.dateparse import parse_date

            day = parse_date(value)
            if day:
                movements = movements.filter(**{lookup: day})
    return movements


def consumption(item, limit=30):
    """Sorties (OT et hors OT) de l'article, nettes des retours, les plus récentes d'abord."""
    return (StockMovement.objects.filter(item=item, kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN])
            .select_related("work_order", "equipment", "warehouse", "created_by")[:limit])


def search_items(query, limit):
    items = Item.objects.filter(
        Q(reference__icontains=query) | Q(designation__icontains=query) | Q(manufacturer_reference__icontains=query)
    ).filter(is_active=True)
    results = []
    for item in items_with_stock(items).order_by("reference")[:limit]:
        results.append(SearchResult(
            category=_("Articles"), title=f"{item.reference} · {item.designation}",
            subtitle=_("Disponible : %(q)s %(u)s") % {"q": f"{item.available.normalize():f}".replace(".", ","), "u": item.get_unit_display()},
            url=reverse("inventory:item_detail", args=[item.pk]),
            badge=_("sous le minimum") if item.below_min else "", badge_class="b-orange" if item.below_min else "",
        ))
    return results
