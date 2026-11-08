"""Paramètres des tests : PostgreSQL dans Docker (SQLite en mémoire sinon), hachage rapide des mots de passe."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
# Dans Docker, les tests tournent sur PostgreSQL, comme en production (base temporaire « test_<nom> »,
# créée puis supprimée par Django) : certains comportements, comme le verrouillage des lignes,
# n'existent pas sous SQLite. Hors Docker, SQLite en mémoire suffit pour un essai rapide.
if not env("POSTGRES_DB"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
ALLOWED_HOSTS = ["testserver", "localhost", ".easymaint.test"]
# Pas de cache entre les tests : chaque test voit des indicateurs recalculés.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
# Les tests sont écrits pour une installation en français, quelle que soit la langue du .env.
LANGUAGE_CODE = "fr"
