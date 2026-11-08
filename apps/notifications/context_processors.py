from .services import unread


def notifications(request):
    """Nombre de notifications non lues et les plus récentes, pour la cloche de la barre supérieure."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or getattr(request, "tenant", None) is None:
        return {}
    queryset = unread(user)
    latest = list(queryset[:6])
    count = len(latest) if len(latest) < 6 else queryset.count()
    return {"notif_unread_count": count, "notif_latest": latest}
