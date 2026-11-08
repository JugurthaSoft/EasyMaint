"""
Données du tableau de bord initial (phase 2) : uniquement ce que la base contient
réellement à ce stade, c'est-à-dire le patrimoine et ses compteurs. Les
indicateurs de maintenance (OT, MTBF, MTTR, disponibilité, coûts) s'ajouteront
avec les modules correspondants.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.assets.models import Equipment, Location, Meter
from apps.core.models import AuditLog

STALE_METER_DAYS = 30


def equipment_summary():
    active = Equipment.objects.exclude(status=Equipment.Status.RETIRED)
    by_status = dict(active.values_list("status").annotate(n=Count("pk")))
    return {
        "total": sum(by_status.values()),
        "in_service": by_status.get(Equipment.Status.IN_SERVICE, 0),
        "broken": by_status.get(Equipment.Status.BROKEN, 0),
        "stopped": by_status.get(Equipment.Status.STOPPED, 0),
        "critical": active.filter(criticality=Equipment.Criticality.A).count(),
        "critical_broken": active.filter(criticality=Equipment.Criticality.A, status=Equipment.Status.BROKEN).count(),
    }


def equipment_by_workshop():
    """
    Répartition des équipements (hors réformés) par unité et par état.
    Un équipement est rattaché au premier ancêtre de type « unité » de sa
    localisation ; à défaut, à sa localisation racine.
    """
    locations = {loc.pk: loc for loc in Location.objects.all()}

    def group_of(location_id):
        node, seen, root = locations.get(location_id), set(), None
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            if node.kind == Location.Kind.WORKSHOP:
                return node
            root = node
            node = locations.get(node.parent_id)
        return root

    rows = (
        Equipment.objects.exclude(status=Equipment.Status.RETIRED)
        .values("location_id", "status").annotate(n=Count("pk"))
    )
    groups = {}
    for row in rows:
        group = group_of(row["location_id"])
        label = group.name if group else "—"
        bucket = groups.setdefault(label, {"in_service": 0, "stopped": 0, "broken": 0})
        bucket[row["status"]] = bucket.get(row["status"], 0) + row["n"]
    ordered = sorted(groups.items(), key=lambda item: -sum(item[1].values()))
    return {
        "labels": [label for label, _counts in ordered],
        "in_service": [counts["in_service"] for _label, counts in ordered],
        "stopped": [counts["stopped"] for _label, counts in ordered],
        "broken": [counts["broken"] for _label, counts in ordered],
    }


def stale_meters(limit=6):
    threshold = timezone.now() - timedelta(days=STALE_METER_DAYS)
    queryset = (
        Meter.objects.exclude(equipment__status=Equipment.Status.RETIRED)
        .filter(Q(last_reading_at__isnull=True) | Q(last_reading_at__lt=threshold))
        .select_related("equipment").order_by("last_reading_at")
    )
    return queryset.count(), list(queryset[:limit])


def broken_equipment(limit=6):
    return list(
        Equipment.objects.filter(status=Equipment.Status.BROKEN)
        .select_related("location").order_by("criticality", "code")[:limit]
    )


def recent_changes(tenant, limit=8):
    labels = [Equipment._meta.label, Location._meta.label, Meter._meta.label]
    return list(
        AuditLog.objects.filter(tenant=tenant, object_type__in=labels)
        .exclude(action=AuditLog.Action.EXPORT).select_related("user")[:limit]
    )
