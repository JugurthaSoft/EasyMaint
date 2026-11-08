"""
Paramètres communs d'EasyMaint.

Toute valeur qui dépend de l'installation (base de données, clé secrète, mode
de déploiement) est lue dans les variables d'environnement : le même code sert
en installation locale (on-premise) et en mode SaaS.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "oui", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# Version affichée dans l'application (« À propos », menu) ; suivre docs/CHANGELOG.md.
EASYMAINT_VERSION = "1.1.0"
# Adresse publique du code source (dépôt Git). La licence AGPL-3.0 impose de proposer le code source
# aux utilisateurs d'une version modifiée accessible par le réseau : la page « À propos » l'affiche.
EASYMAINT_SOURCE_URL = env("EASYMAINT_SOURCE_URL", "https://github.com/jugurthasoft/easymaint")

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# "onprem" : une seule entreprise, résolue depuis l'utilisateur connecté.
# "saas"   : plusieurs entreprises ; le sous-domaine doit correspondre à l'entreprise de l'utilisateur.
DEPLOYMENT_MODE = env("EASYMAINT_DEPLOYMENT_MODE", "onprem")
SAAS_BASE_DOMAIN = env("EASYMAINT_SAAS_BASE_DOMAIN", "")
if DEPLOYMENT_MODE == "saas" and "web" not in ALLOWED_HOSTS:
    # Caddy interroge l'application en interne (http://web:8000) avant d'émettre un certificat.
    ALLOWED_HOSTS.append("web")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "rest_framework.authtoken",
    # Applications EasyMaint (ordre = dépendances)
    "apps.core",
    "apps.accounts",
    "apps.assets",
    "apps.workforce",
    "apps.workorders",
    "apps.inventory",
    "apps.preventive",
    "apps.condition",
    "apps.finance",
    "apps.kpi",
    "apps.imports",
    "apps.notifications",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.easymaint",
                "apps.notifications.context_processors.notifications",
            ],
        },
    },
]

# Base de données : PostgreSQL en production, SQLite accepté pour un premier essai.
if env("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "easymaint"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "db"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Sessions : expiration après 8 h d'inactivité (un poste de travail)
SESSION_COOKIE_AGE = int(env("EASYMAINT_SESSION_HOURS", "8")) * 3600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # HTMX lit le jeton depuis la balise meta, pas le cookie
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Protection contre les essais de mots de passe : après N échecs en M minutes pour un même
# identifiant, la connexion est bloquée M minutes. Une même adresse IP est bloquée après 4 × N échecs
# (plusieurs postes d'une usine peuvent sortir par la même adresse).
EASYMAINT_LOGIN_MAX_FAILURES = int(env("EASYMAINT_LOGIN_MAX_FAILURES", "5"))
EASYMAINT_LOGIN_LOCK_MINUTES = int(env("EASYMAINT_LOGIN_LOCK_MINUTES", "15"))
# Derrière un proxy de confiance (Caddy en SaaS), l'adresse du client est lue dans X-Forwarded-For.
EASYMAINT_BEHIND_PROXY = env_bool("EASYMAINT_BEHIND_PROXY", False)

# Sécurité des réponses (valables aussi sans HTTPS)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Cache local (mémoire du processus) : indicateurs du tableau de bord recalculés au plus toutes les 10 min.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "easymaint"}}
EASYMAINT_DASHBOARD_CACHE_SECONDS = int(env("EASYMAINT_DASHBOARD_CACHE_SECONDS", "600"))

# Langue et formats (dates JJ/MM/AAAA dans toutes les langues)
# Langue de l'installation, choisie une fois pour toutes à l'installation (EASYMAINT_LANGUAGE dans le .env) :
# toute l'entreprise travaille dans cette langue (écrans, documents, exports, rapports).
# Langues disponibles : français (référence) et anglais ; l'arabe viendra avec sa traduction.
AVAILABLE_LANGUAGES = {"fr": "Français", "en": "English"}
LANGUAGE_CODE = env("EASYMAINT_LANGUAGE", "fr").strip().lower()
if LANGUAGE_CODE not in AVAILABLE_LANGUAGES:
    LANGUAGE_CODE = "fr"
LANGUAGES = list(AVAILABLE_LANGUAGES.items())
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = env("EASYMAINT_TIME_ZONE", "Africa/Tunis")
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["config.formats"]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("EASYMAINT_MEDIA_ROOT", str(BASE_DIR / "media")))
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
EASYMAINT_MAX_ATTACHMENT_MB = int(env("EASYMAINT_MAX_ATTACHMENT_MB", "25"))
# Sauvegardes automatiques (service Docker « backup ») : dossier lu par la page « Sauvegardes ».
EASYMAINT_BACKUP_DIR = Path(env("EASYMAINT_BACKUP_DIR", str(BASE_DIR / "sauvegardes")))
EASYMAINT_BACKUP_HOUR = int(env("EASYMAINT_BACKUP_HOUR", "1"))
EASYMAINT_BACKUP_KEEP_DAYS = int(env("EASYMAINT_BACKUP_KEEP_DAYS", "14"))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("EASYMAINT_LOG_LEVEL", "INFO")},
    "loggers": {
        "easymaint": {"handlers": ["console"], "level": env("EASYMAINT_LOG_LEVEL", "INFO"), "propagate": False},
    },
}
