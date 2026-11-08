"""Socle commun des vues API : entreprise courante posée après l'authentification DRF."""
from django.conf import settings
from django.utils.translation import gettext
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from .middleware import subdomain_of
from .tenancy import reset_current_tenant, set_current_tenant


class TenantAPIMixin:
    """
    Le middleware ne connaît que l'utilisateur de session. Avec un jeton (capteurs, ERP…),
    l'utilisateur n'est connu qu'après l'authentification DRF : l'entreprise courante est
    donc posée ici, puis retirée en fin de requête. Mêmes contrôles que le middleware.
    """

    _tenant_token = None

    def perform_authentication(self, request):
        super().perform_authentication(request)
        user = request.user
        tenant = getattr(user, "tenant", None) if user and user.is_authenticated else None
        if tenant is not None:
            if not tenant.is_active:
                raise AuthenticationFailed(gettext("Entreprise désactivée."))
            if settings.DEPLOYMENT_MODE == "saas":
                sub = subdomain_of(request.get_host())
                if sub is not None and sub != tenant.code:
                    raise PermissionDenied(gettext("Ce compte n'appartient pas à cette entreprise."))
        request._request.tenant = tenant
        self._tenant_token = set_current_tenant(tenant)

    def finalize_response(self, request, response, *args, **kwargs):
        if self._tenant_token is not None:
            reset_current_tenant(self._tenant_token)
            self._tenant_token = None
        return super().finalize_response(request, response, *args, **kwargs)
