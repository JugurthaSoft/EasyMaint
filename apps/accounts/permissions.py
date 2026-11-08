"""Contrôle d'accès par capacité, côté vues web et côté API."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission


class CapabilityRequiredMixin(LoginRequiredMixin):
    """
    Vue réservée aux utilisateurs ayant `required_capability`.
    Un utilisateur sans entreprise (super-administrateur plateforme) est refusé.
    """

    required_capability = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.tenant_id is None:
            raise PermissionDenied
        if self.required_capability and not request.user.has_capability(self.required_capability):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def require_capability(user, code):
    if not user.has_capability(code):
        raise PermissionDenied


class HasCapability(BasePermission):
    """
    Permission DRF : `read_capability` pour les lectures, `write_capability` pour
    les écritures, déclarées sur la vue.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or user.tenant_id is None:
            return False
        code = getattr(view, "read_capability", None) if request.method in SAFE_METHODS else getattr(view, "write_capability", None)
        return bool(code) and user.has_capability(code)
