from .navigation import NAVIGATION, SETTINGS_NAVIGATION, build_menu


def easymaint(request):
    """Variables communes à toutes les pages : entreprise, menu filtré par les droits."""
    from django.conf import settings

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"tenant": None, "easymaint_version": settings.EASYMAINT_VERSION}
    resolver = getattr(request, "resolver_match", None)
    active = getattr(request, "nav_active", None)
    if active is None and resolver is not None:
        active = resolver.url_name and _guess_active(resolver.namespace, resolver.url_name)
    return {
        "easymaint_version": settings.EASYMAINT_VERSION,
        "tenant": getattr(request, "tenant", None),
        "main_menu": build_menu(user, NAVIGATION, active),
        "settings_menu": build_menu(user, SETTINGS_NAVIGATION, active),
    }


def _guess_active(namespace, url_name):
    if namespace == "dashboard":
        return "home"
    if namespace == "core" and url_name == "backups":
        return "backups"
    if namespace == "assets":
        if url_name.startswith("location"):
            return "locations"
        if url_name.startswith(("family", "manufacturer")):
            return "referentials"
        return "equipment"
    if namespace == "workorders":
        if url_name.startswith("request"):
            return "requests"
        if url_name.startswith("failure"):
            return "failure_codes"
        if url_name in ("my_work_orders", "wo_execute"):
            return "my_orders"
        return "work_orders"
    if namespace == "preventive":
        if url_name == "planning":
            return "planning"
        if url_name == "wo_postpone":
            return "work_orders"
        return "preventive"
    if namespace == "condition":
        return "condition"
    if namespace == "inventory":
        return "inventory"
    if namespace == "finance":
        return "finance"
    if namespace == "kpi":
        return "kpi"
    if namespace == "imports":
        return "imports"
    if namespace == "workforce":
        return "workforce"
    if namespace == "accounts":
        if url_name.startswith("role"):
            return "roles"
        if url_name.startswith("audit"):
            return "audit"
        if url_name.startswith("user"):
            return "users"
    return None
