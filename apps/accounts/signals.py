"""Journal des connexions : réussites, échecs, déconnexions."""
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from apps.core.models import AuditLog
from apps.core.services import log_action


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_action(AuditLog.Action.LOGIN, user=user, request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log_action(AuditLog.Action.LOGOUT, user=user, request=request)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    log_action(AuditLog.Action.LOGIN_FAILED, request=request, username=str(credentials.get("username", "")))
