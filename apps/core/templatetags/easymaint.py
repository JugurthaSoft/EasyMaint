"""Filtres et balises de gabarit d'EasyMaint."""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext

from apps.core.formatting import format_money, format_number, smart_number
from apps.core.tenancy import get_current_tenant

register = template.Library()

# Icônes au trait (24×24), dessinées en ligne : aucune police d'icônes à charger.
ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "repeat": '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "inbox": '<path d="M4 4h16v16H4z"/><path d="M4 14h5l1 2h4l1-2h5"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "equipment": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>',
    "location": '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a5.5 5.5 0 0 1 3.5 6"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/>',
    "tag": '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M4 20h16"/>',
    "printer": '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
    "wallet": '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><path d="M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2z"/><circle cx="16" cy="14.5" r="1.2"/>',
    "box": '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>',
    "upload": '<path d="M12 20V9M7 14l5-5 5 5M4 4h16"/>',
    "qr": '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z"/><path d="M14 14h2v2h-2zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z"/>',
    "gauge": '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4-5"/>',
    "file": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>',
    "logout": '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "chevron": '<path d="M9 6l6 6-6 6"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
}


@register.simple_tag
def icon(name, size=18, label=""):
    paths = ICONS.get(name, "")
    aria = format_html('role="img" aria-label="{}"', label) if label else mark_safe('aria-hidden="true"')
    return format_html(
        '<svg class="icon" width="{}" height="{}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" {}>{}</svg>',
        size, size, aria, mark_safe(paths),
    )


@register.filter
def money(value):
    """Montant dans la devise de l'entreprise courante (TND, 3 décimales par défaut)."""
    tenant = get_current_tenant()
    currency = getattr(tenant, "currency_code", "TND")
    decimals = getattr(tenant, "currency_decimals", 3)
    return format_money(value, currency, decimals)


@register.filter
def number(value, decimals=None):
    if decimals is None or decimals == "":
        return smart_number(value)
    return format_number(value, int(decimals))


@register.filter
def filesize(value):
    if not value:
        return gettext("%(n)s Ko") % {"n": 0}
    value = float(value)
    if value < 1024 * 1024:
        return gettext("%(n)s Ko") % {"n": format_number(value / 1024, 0)}
    return gettext("%(n)s Mo") % {"n": format_number(value / (1024 * 1024), 1)}


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def can(user, capability):
    """{% if user|can:"assets.manage" %} : affiche une action seulement si elle est autorisée."""
    return bool(user and user.is_authenticated and user.has_capability(capability))


@register.filter
def is_checkbox(bound_field):
    return bound_field.field.widget.__class__.__name__ == "CheckboxInput"


@register.filter
def bs(bound_field):
    """Rend un champ de formulaire avec les classes Bootstrap adaptées à son widget."""
    widget = bound_field.field.widget.__class__.__name__
    if widget == "CheckboxInput":
        css = "form-check-input"
    elif widget in ("Select", "SelectMultiple", "NullBooleanSelect"):
        css = "form-select"
    elif widget in ("CheckboxSelectMultiple", "RadioSelect"):
        css = ""
    else:
        css = "form-control"
    if bound_field.errors:
        css += " is-invalid"
    attrs = {"class": css.strip()} if css.strip() else {}
    if bound_field.help_text:
        attrs["aria-describedby"] = f"{bound_field.auto_id}_help"
    return bound_field.as_widget(attrs=attrs)
