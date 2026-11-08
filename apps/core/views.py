from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import require_capability

from .search import search_all


@login_required
def global_search(request):
    """
    Recherche globale. Appelée en HTMX depuis la barre supérieure (liste déroulante),
    ou en page complète avec Entrée.
    """
    query = request.GET.get("q", "")
    results = search_all(request.user, query)
    template = "core/_search_dropdown.html" if request.headers.get("HX-Request") else "core/search_results.html"
    return render(request, template, {"query": query, "results": results})


@login_required
def backups(request):
    """
    État des sauvegardes automatiques (installation locale uniquement) : dates, tailles, alerte si la
    dernière date de plus de 2 jours. Aucun téléchargement depuis l'application : les fichiers contiennent
    toute la base et se récupèrent directement dans le dossier « sauvegardes » du serveur.
    """
    require_capability(request.user, "settings.manage")
    if settings.DEPLOYMENT_MODE != "onprem":
        raise Http404
    folder = settings.EASYMAINT_BACKUP_DIR
    files = []
    if folder.is_dir():
        for path in folder.iterdir():
            if path.is_file() and path.name.startswith("easymaint-") and not path.name.endswith(".part"):
                stat = path.stat()
                files.append({
                    "name": path.name, "size": stat.st_size,
                    "kind": "base" if "-db-" in path.name else "fichiers",
                    "at": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc),
                })
    files.sort(key=lambda f: f["at"], reverse=True)
    latest = next((f for f in files if f["kind"] == "base"), None)
    return render(request, "core/backups.html", {
        "files": files[:60], "latest": latest, "folder_found": folder.is_dir(),
        "stale": latest is None or timezone.now() - latest["at"] > timedelta(days=2),
        "keep_days": settings.EASYMAINT_BACKUP_KEEP_DAYS, "hour": settings.EASYMAINT_BACKUP_HOUR,
    })


# Composants libres utilisés par EasyMaint et leurs licences (affichés dans « À propos »).
COMPONENTS = [
    ("Django", "BSD-3-Clause"), ("Django REST framework", "BSD-3-Clause"), ("PostgreSQL / psycopg", "PostgreSQL / LGPL-3.0"),
    ("Bootstrap", "MIT"), ("HTMX", "0BSD"), ("Chart.js", "MIT"), ("ReportLab", "BSD-3-Clause"), ("openpyxl", "MIT"),
    ("Pillow", "MIT-CMU"), ("qrcode", "BSD-3-Clause"), ("WhiteNoise", "MIT"), ("Gunicorn", "MIT"), ("Caddy (SaaS)", "Apache-2.0"),
]


def about(request):
    """Version, licence AGPL-3.0, code source et composants. Page publique : aucune donnée de l'entreprise."""
    return render(request, "core/about.html", {
        "version": settings.EASYMAINT_VERSION, "source_url": settings.EASYMAINT_SOURCE_URL, "components": COMPONENTS,
    })


def tls_check(request):
    """
    Mode SaaS : Caddy demande ici s'il peut obtenir un certificat HTTPS pour un nom de domaine.
    Seuls le domaine principal et les sous-domaines des entreprises actives sont acceptés : personne ne
    peut faire émettre des certificats pour des noms inventés.
    """
    from .models import Tenant

    base = settings.SAAS_BASE_DOMAIN.strip().lower()
    domain = request.GET.get("domain", "").strip().lower().rstrip(".")
    if settings.DEPLOYMENT_MODE != "saas" or not base or not domain:
        raise Http404
    if domain in (base, f"www.{base}"):
        return HttpResponse("ok")
    if domain.endswith("." + base):
        code = domain[: -len(base) - 1]
        if "." not in code and Tenant.objects.filter(code=code, is_active=True).exists():
            return HttpResponse("ok")
    raise Http404


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)
