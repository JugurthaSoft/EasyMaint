"""
Recherche globale extensible.

Chaque module enregistre un fournisseur au démarrage (AppConfig.ready). Le
module OT de la phase 3 et le module stock de la phase 5 ajouteront le leur,
sans modifier le socle.
"""
from dataclasses import dataclass

_providers = []


@dataclass
class SearchResult:
    category: str
    title: str
    subtitle: str
    url: str
    badge: str = ""
    badge_class: str = ""


def register_provider(provider, *, capability=None):
    """`provider(query, limit)` renvoie une liste de SearchResult pour l'entreprise courante."""
    _providers.append((provider, capability))


def search_all(user, query, limit_per_provider=8):
    query = (query or "").strip()
    if len(query) < 2:
        return []
    results = []
    for provider, capability in _providers:
        if capability and not user.has_capability(capability):
            continue
        results.extend(provider(query, limit_per_provider))
    return results
