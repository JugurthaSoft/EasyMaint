from django.contrib import admin
from django.urls import include, path

from apps.core.views import tls_check

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path("compte/", include("apps.accounts.urls")),
    path("equipements/", include("apps.assets.urls")),
    path("interventions/", include("apps.workorders.urls")),
    path("equipes/", include("apps.workforce.urls")),
    path("preventif/", include("apps.preventive.urls")),
    path("magasin/", include("apps.inventory.urls")),
    path("couts/", include("apps.finance.urls")),
    path("indicateurs/", include("apps.kpi.urls")),
    path("imports/", include("apps.imports.urls")),
    path("conditionnel/", include("apps.condition.urls")),
    path("", include("apps.core.urls")),  # recherche, sauvegardes, à propos
    path("notifications/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.condition.api_urls")),
    path("api/v1/", include("apps.assets.api.urls")),
    path("admin-plateforme/", admin.site.urls),
    # Interrogée par Caddy (SaaS) avant d'émettre un certificat HTTPS ; bloquée depuis l'extérieur.
    path("interne/tls/", tls_check, name="tls_check"),
]

# Les fichiers envoyés (photos, documents) ne sont jamais servis directement :
# ils passent par des vues qui vérifient l'entreprise et les droits.

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
