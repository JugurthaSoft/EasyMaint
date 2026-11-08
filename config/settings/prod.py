"""Paramètres de production (on-premise ou SaaS)."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import EASYMAINT_BEHIND_PROXY, SECRET_KEY, env_bool

DEBUG = False

if SECRET_KEY == "dev-insecure-change-me" or len(SECRET_KEY) < 40:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être défini (au moins 40 caractères) en production.")

# HTTPS : obligatoire en SaaS, optionnel sur un réseau local sans certificat.
USE_HTTPS = env_bool("EASYMAINT_USE_HTTPS", False)
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
SECURE_SSL_REDIRECT = USE_HTTPS
# Appel interne de Caddy (http://web:8000/interne/tls/) : pas de redirection vers HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^interne/"]
# L'en-tête X-Forwarded-Proto n'est cru que s'il est posé par un proxy de confiance. En HTTPS, il y en a
# forcément un (Gunicorn ne chiffre pas lui-même) : c'est lui qui termine le chiffrement.
if EASYMAINT_BEHIND_PROXY or USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if USE_HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = USE_HTTPS
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
