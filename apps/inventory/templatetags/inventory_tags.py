from django import template

from apps.inventory.models import Item

register = template.Library()


@register.inclusion_tag("inventory/_items_datalist.html")
def items_datalist():
    """Liste de suggestions des articles actifs (référence · désignation) pour les champs « Article »."""
    return {"datalist_items": Item.objects.filter(is_active=True).only("reference", "designation").order_by("reference")}
