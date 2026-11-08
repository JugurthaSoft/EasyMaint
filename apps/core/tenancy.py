"""
Entreprise (tenant) courante.

La séparation des données entre entreprises repose sur une seule règle :
toute requête sur un modèle multi-entreprise passe par `TenantManager`, qui
filtre sur l'entreprise courante. Sans entreprise courante, le manager ne
renvoie RIEN (queryset vide) : un oubli ne peut donc pas exposer les données
d'une autre entreprise.

L'entreprise courante est posée par `TenantMiddleware` pour chaque requête web,
et par `tenant_context()` dans les commandes et les tests.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_current_tenant = ContextVar("easymaint_current_tenant", default=None)
_current_user = ContextVar("easymaint_current_user", default=None)


def get_current_tenant():
    return _current_tenant.get()


def set_current_tenant(tenant):
    """Pose l'entreprise courante et renvoie le jeton à passer à `reset_current_tenant`."""
    return _current_tenant.set(tenant)


def reset_current_tenant(token):
    _current_tenant.reset(token)


@contextmanager
def tenant_context(tenant):
    """Exécute un bloc de code dans le contexte d'une entreprise donnée."""
    token = _current_tenant.set(tenant)
    try:
        yield tenant
    finally:
        _current_tenant.reset(token)


def get_current_user():
    """Utilisateur à l'origine de la requête web en cours (None pour le planificateur et les commandes)."""
    return _current_user.get()


def set_current_user(user):
    return _current_user.set(user)


def reset_current_user(token):
    _current_user.reset(token)
