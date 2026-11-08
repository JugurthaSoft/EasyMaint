"""Lectures du patrimoine (arborescences, filtres, recherche). Toujours limitées à l'entreprise courante."""
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.translation import gettext

from apps.core.search import SearchResult

from .models import Equipment, Location


def location_paths():
    """{id: "Usine › Unité › Ligne"} pour toutes les localisations, en une seule requête."""
    nodes = {loc.pk: loc for loc in Location.objects.all()}
    paths = {}

    def path_of(pk, depth=0):
        if pk in paths:
            return paths[pk]
        node = nodes[pk]
        if node.parent_id and node.parent_id in nodes and depth < 20:
            paths[pk] = f"{path_of(node.parent_id, depth + 1)} › {node.name}"
        else:
            paths[pk] = node.name
        return paths[pk]

    for pk in nodes:
        path_of(pk)
    return paths


def descendant_location_ids(location_id):
    """L'identifiant donné et tous ceux de ses descendants."""
    children = {}
    for pk, parent_id in Location.objects.values_list("pk", "parent_id"):
        children.setdefault(parent_id, []).append(pk)
    result, stack = [], [location_id]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.append(current)
        stack.extend(children.get(current, []))
    return result


def location_tree():
    """Arbre des localisations avec, pour chaque nœud, le nombre d'équipements (descendants compris)."""
    locations = list(Location.objects.annotate(direct_count=Count("equipment")).order_by("name"))
    by_parent = {}
    for loc in locations:
        by_parent.setdefault(loc.parent_id, []).append(loc)

    def build(parent_id, depth=0, seen=None):
        seen = seen or set()
        nodes = []
        for loc in by_parent.get(parent_id, []):
            if loc.pk in seen:
                continue
            children = build(loc.pk, depth + 1, seen | {loc.pk})
            total = loc.direct_count + sum(child["total"] for child in children)
            nodes.append({"location": loc, "children": children, "total": total, "depth": depth})
        return nodes

    return build(None)


def location_choices(exclude_ids=()):
    """Choix (id, chemin complet) triés par chemin, pour les listes déroulantes."""
    paths = location_paths()
    active = set(Location.objects.filter(is_active=True).values_list("pk", flat=True))
    return sorted(
        ((pk, path) for pk, path in paths.items() if pk in active and pk not in exclude_ids),
        key=lambda item: item[1].lower(),
    )


def filter_equipment(params):
    """Équipements filtrés selon les paramètres de la liste (q, statut, criticite, localisation, famille)."""
    queryset = Equipment.objects.select_related("location", "family", "family__parent", "manufacturer")
    query = (params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(code__icontains=query) | Q(designation__icontains=query) | Q(serial_number__icontains=query)
            | Q(model__icontains=query) | Q(brand__icontains=query) | Q(manufacturer__name__icontains=query)
        )
    status = params.get("statut")
    if status in Equipment.Status.values:
        queryset = queryset.filter(status=status)
    elif not status:
        queryset = queryset.exclude(status=Equipment.Status.RETIRED)
    criticality = params.get("criticite")
    if criticality in Equipment.Criticality.values:
        queryset = queryset.filter(criticality=criticality)
    location = params.get("localisation")
    if location and str(location).isdigit():
        queryset = queryset.filter(location_id__in=descendant_location_ids(int(location)))
    family = params.get("famille")
    if family and str(family).isdigit():
        queryset = queryset.filter(Q(family_id=int(family)) | Q(family__parent_id=int(family)))
    return queryset.order_by("code")


def status_counts():
    counts = dict(Equipment.objects.values_list("status").annotate(n=Count("pk")))
    return {status: counts.get(status, 0) for status in Equipment.Status.values}


# --- Fournisseurs de la recherche globale ------------------------------------------

def search_equipment(query, limit):
    paths = None
    results = []
    matches = Equipment.objects.filter(
        Q(code__icontains=query) | Q(designation__icontains=query) | Q(serial_number__icontains=query)
        | Q(model__icontains=query)
    ).select_related("location").order_by("code")[:limit]
    for equipment in matches:
        if paths is None:
            paths = location_paths()
        results.append(SearchResult(
            category=gettext("Équipements"),
            title=str(equipment),
            subtitle=paths.get(equipment.location_id, ""),
            url=equipment.get_absolute_url(),
            badge=equipment.get_status_display(),
            badge_class=equipment.status_badge,
        ))
    return results


def search_locations(query, limit):
    paths = None
    results = []
    for location in Location.objects.filter(Q(code__icontains=query) | Q(name__icontains=query))[:limit]:
        if paths is None:
            paths = location_paths()
        results.append(SearchResult(
            category=gettext("Localisations"),
            title=location.name,
            subtitle=paths.get(location.pk, ""),
            url=f"{reverse('assets:equipment_list')}?localisation={location.pk}",
            badge=location.get_kind_display(),
            badge_class="b-gray",
        ))
    return results
