"""
Création et lecture des notifications.

Une notification ne doit jamais faire échouer l'action métier qui la déclenche : toute erreur
est journalisée puis ignorée (point de sauvegarde dans la transaction en cours).
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.tenancy import get_current_user

from .models import Notification

logger = logging.getLogger("easymaint")

# Durées de conservation : notifications lues, puis toutes les notifications.
KEEP_READ_DAYS = 90
KEEP_ALL_DAYS = 365


def users_with(tenant, capability):
    """Utilisateurs actifs de l'entreprise disposant de la capacité."""
    users = get_user_model().objects.filter(tenant=tenant, is_active=True, role__isnull=False).select_related("role")
    return [user for user in users if user.has_capability(capability)]


def notify(users, *, tenant, kind, title, body="", url=""):
    """Crée une notification pour chaque destinataire, sauf l'auteur de l'action."""
    if tenant is None:
        return 0
    actor = get_current_user()
    recipients, seen = [], set()
    for user in users:
        if user is None or not user.is_active or user.pk in seen or user.tenant_id != tenant.pk:
            continue
        if actor is not None and actor.pk == user.pk:
            continue
        seen.add(user.pk)
        recipients.append(user)
    if not recipients:
        return 0
    try:
        with transaction.atomic():
            Notification.all_tenants.bulk_create([
                Notification(tenant=tenant, user=user, kind=kind, title=str(title)[:200], body=str(body)[:255], url=url[:300])
                for user in recipients
            ])
    except Exception:
        logger.exception("Échec de création d'une notification")
        return 0
    return len(recipients)


def unread(user):
    return Notification.objects.filter(user=user, read_at__isnull=True)


def mark_read(user, pk=None):
    queryset = unread(user)
    if pk is not None:
        queryset = queryset.filter(pk=pk)
    return queryset.update(read_at=timezone.now())


def purge(now=None):
    """Supprime les notifications anciennes (appelé chaque nuit par le planificateur)."""
    now = now or timezone.now()
    read, _ = Notification.all_tenants.filter(read_at__isnull=False, created_at__lt=now - timedelta(days=KEEP_READ_DAYS)).delete()
    old, _ = Notification.all_tenants.filter(created_at__lt=now - timedelta(days=KEEP_ALL_DAYS)).delete()
    return read + old
