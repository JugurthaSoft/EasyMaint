"""
Menu latéral. Chaque entrée n'apparaît que si l'utilisateur a la capacité requise
et si le module est livré (`url_name` renseigné). Les modules des phases
suivantes s'ajoutent ici au fur et à mesure.
"""
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

NAVIGATION = [
    {"key": "home", "label": _("Accueil"), "icon": "home", "url_name": "dashboard:home", "capability": None},
    {"key": "my_orders", "label": _("Mes interventions"), "icon": "user", "url_name": "workorders:my_work_orders", "capability": "workorders.execute", "technician_only": True},
    {"key": "requests", "label": _("Demandes"), "icon": "inbox", "url_name": "workorders:request_list", "capability": "requests.create"},
    {"key": "work_orders", "label": _("Ordres de travail"), "icon": "wrench", "url_name": "workorders:wo_list", "capability": "workorders.view"},
    {"key": "planning", "label": _("Planning"), "icon": "calendar", "url_name": "preventive:planning", "capability": "workorders.view"},
    {"key": "preventive", "label": _("Préventif"), "icon": "repeat", "url_name": "preventive:plan_list", "capability": "preventive.view"},
    {"key": "condition", "label": _("Conditionnel"), "icon": "pulse", "url_name": "condition:overview", "capability": "condition.view"},
    {"key": "inventory", "label": _("Magasin"), "icon": "box", "url_name": "inventory:item_list", "capability": "inventory.view"},
    {"key": "kpi", "label": _("Indicateurs"), "icon": "gauge", "url_name": "kpi:indicators", "capability": "kpi.view"},
    {"key": "finance", "label": _("Coûts et budget"), "icon": "wallet", "url_name": "finance:costs", "capability": "costs.view"},
    {"key": "equipment", "label": _("Équipements"), "icon": "equipment", "url_name": "assets:equipment_list", "capability": "assets.view"},
    {"key": "locations", "label": _("Localisations"), "icon": "location", "url_name": "assets:location_tree", "capability": "assets.view"},
    {"key": "workforce", "label": _("Équipes"), "icon": "users", "url_name": "workforce:technician_list", "capability": "workforce.view"},
]

SETTINGS_NAVIGATION = [
    {"key": "users", "label": _("Utilisateurs"), "icon": "users", "url_name": "accounts:user_list", "capability": "settings.manage"},
    {"key": "roles", "label": _("Rôles et droits"), "icon": "shield", "url_name": "accounts:role_list", "capability": "settings.manage"},
    {"key": "referentials", "label": _("Familles et fabricants"), "icon": "tag", "url_name": "assets:family_list", "capability": "assets.manage"},
    {"key": "failure_codes", "label": _("Codes de défaillance"), "icon": "tag", "url_name": "workorders:failure_codes", "capability": "workorders.manage"},
    {"key": "imports", "label": _("Imports de données"), "icon": "upload", "url_name": "imports:home", "capability": "imports.run"},
    {"key": "audit", "label": _("Journal d'activité"), "icon": "history", "url_name": "accounts:audit_list", "capability": "audit.view"},
    {"key": "backups", "label": _("Sauvegardes"), "icon": "download", "url_name": "core:backups", "capability": "settings.manage", "onprem_only": True},
]


def _is_technician(user):
    """Vrai si le compte est relié à une fiche technicien (module workforce, s'il est installé)."""
    technician = getattr(user, "technician", None) if hasattr(user, "technician") else None
    return technician is not None and technician.is_active


def build_menu(user, entries, active_key):
    menu = []
    for entry in entries:
        if entry["capability"] and not user.has_capability(entry["capability"]):
            continue
        if entry.get("technician_only") and not _is_technician(user):
            continue
        if entry.get("onprem_only") and settings.DEPLOYMENT_MODE != "onprem":
            continue
        try:
            url = reverse(entry["url_name"])
        except NoReverseMatch:
            continue
        menu.append({**entry, "url": url, "active": entry["key"] == active_key})
    return menu
