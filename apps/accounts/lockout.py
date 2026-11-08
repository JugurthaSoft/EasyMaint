"""
Blocage temporaire de la connexion après plusieurs échecs (protection contre les essais de mots de passe).

S'appuie sur le journal d'audit (échecs de connexion déjà enregistrés), sans table supplémentaire :
- un identifiant est bloqué après N échecs en M minutes (depuis sa dernière connexion réussie) ;
- une adresse IP est bloquée après 4 × N échecs en M minutes, tous identifiants confondus.
Le blocage se lève seul au bout de M minutes. Les tentatives faites pendant le blocage ne sont pas
vérifiées (le mot de passe n'est même pas testé).
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.models import AuditLog

IP_FACTOR = 4


def _limits():
    return max(1, settings.EASYMAINT_LOGIN_MAX_FAILURES), timedelta(minutes=max(1, settings.EASYMAINT_LOGIN_LOCK_MINUTES))


def _remaining(times, limit, window, now):
    """Temps restant si au moins `limit` échecs dans la fenêtre : jusqu'à ce que le plus ancien d'entre eux sorte de la fenêtre."""
    if len(times) < limit:
        return None
    unlock = times[limit - 1] + window
    return unlock - now if unlock > now else None


def locked_for(username="", ip=None, now=None):
    """Durée de blocage restante (timedelta) pour cet identifiant ou cette adresse, sinon None."""
    now = now or timezone.now()
    limit, window = _limits()
    since = now - window
    failures = AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, at__gte=since)
    delays = []
    username = (username or "").strip()
    if username:
        last_success = (AuditLog.objects.filter(action=AuditLog.Action.LOGIN, username__iexact=username, at__gte=since)
                        .order_by("-at").values_list("at", flat=True).first())
        mine = failures.filter(username__iexact=username)
        if last_success:
            mine = mine.filter(at__gt=last_success)
        delays.append(_remaining(list(mine.order_by("-at").values_list("at", flat=True)[:limit]), limit, window, now))
    if ip:
        ip_limit = limit * IP_FACTOR
        delays.append(_remaining(list(failures.filter(ip_address=ip).order_by("-at").values_list("at", flat=True)[:ip_limit]),
                                 ip_limit, window, now))
    delays = [d for d in delays if d]
    return max(delays) if delays else None


def minutes(delay):
    return max(1, int((delay.total_seconds() + 59) // 60))
