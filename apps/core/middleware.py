"""Résolution de l'entreprise courante pour chaque requête."""
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect, render

from .tenancy import (
    reset_current_tenant,
    reset_current_user,
    set_current_tenant,
    set_current_user,
)


def subdomain_of(host):
    """Sous-domaine de la requête en mode SaaS (« acme » pour acme.easymaint.tn), sinon None."""
    base = settings.SAAS_BASE_DOMAIN.strip().lower()
    host = host.split(":")[0].lower()
    if base and host.endswith("." + base):
        return host[: -len(base) - 1]
    return None


class TenantMiddleware:
    """
    L'entreprise courante est celle de l'utilisateur connecté.
    En mode SaaS, le sous-domaine doit en plus correspondre à cette entreprise :
    un utilisateur ne peut pas consulter une autre entreprise en changeant d'adresse.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            tenant = user.tenant
            if tenant is not None and not tenant.is_active:
                logout(request)
                return redirect(settings.LOGIN_URL)
            if settings.DEPLOYMENT_MODE == "saas" and tenant is not None:
                sub = subdomain_of(request.get_host())
                if sub is not None and sub != tenant.code:
                    return render(request, "errors/403.html", status=403)
        request.tenant = tenant
        token = set_current_tenant(tenant)
        user_token = set_current_user(user if tenant is not None else None)
        try:
            return self.get_response(request)
        finally:
            reset_current_user(user_token)
            reset_current_tenant(token)


class SecurityHeadersMiddleware:
    """
    En-têtes de sécurité complémentaires à ceux de Django (SecurityMiddleware) :
    politique de sécurité du contenu (CSP) et restrictions des fonctions du navigateur.

    La CSP n'autorise que les scripts servis par EasyMaint lui-même (aucun script en ligne,
    aucun site extérieur) : une injection de code dans une page ne peut pas s'exécuter.
    """

    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # attributs style="" des gabarits et des graphiques
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])
    PERMISSIONS = "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", self.CSP)
        response.headers.setdefault("Permissions-Policy", self.PERMISSIONS)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response
