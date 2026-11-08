"""Lectures du conditionnel : état des points, alertes, recherche."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.search import SearchResult

from .models import (
    LEVEL_RANK,
    Alert,
    Level,
    Measurement,
    MeasurementPoint,
    MeasurementSession,
)


def latest_by_point(points):
    """{(point_id, parameter_id): dernière mesure} pour une liste de points, en une requête par point."""
    latest = {}
    for point in points:
        seen = set()
        for m in Measurement.objects.filter(point=point).select_related("parameter").order_by("-measured_at", "-pk")[:200]:
            key = (point.pk, m.parameter_id)
            if key not in seen:
                seen.add(key)
                latest[key] = m
    return latest


def point_states(equipment):
    """Points de l'équipement avec, pour chaque paramètre, la dernière mesure et son niveau."""
    points = list(equipment.measurement_points.filter(is_active=True).prefetch_related("parameters"))
    latest = latest_by_point(points)
    rows = []
    for point in points:
        params = []
        worst = Level.UNKNOWN
        for parameter in point.parameters.all():
            m = latest.get((point.pk, parameter.pk))
            params.append({"parameter": parameter, "measurement": m})
            if m and LEVEL_RANK.get(m.level, 0) > LEVEL_RANK.get(worst, 0):
                worst = m.level
            elif m and worst == Level.UNKNOWN and m.level == Level.NORMAL:
                worst = Level.NORMAL
        rows.append({"point": point, "params": params, "worst": worst})
    return rows


def active_alerts():
    return (
        Alert.objects.exclude(status=Alert.Status.CLOSED)
        .select_related("point", "point__equipment", "parameter", "last_measurement", "last_measurement__threshold", "work_order", "work_request")
    )


def sort_alerts(alerts):
    return sorted(alerts, key=lambda a: (-LEVEL_RANK.get(a.level, 0), a.status != Alert.Status.OPEN, -a.opened_at.timestamp()))


def overview():
    alerts = list(active_alerts())
    since = timezone.now() - timedelta(days=30)
    return {
        "alerts": sort_alerts(alerts),
        "open": sum(1 for a in alerts if a.status == Alert.Status.OPEN),
        "critical": sum(1 for a in alerts if a.level == Level.CRITICAL),
        "alarm": sum(1 for a in alerts if a.level == Level.ALARM),
        "warning": sum(1 for a in alerts if a.level == Level.WARNING),
        "points": MeasurementPoint.objects.filter(is_active=True).count(),
        "sessions_30": MeasurementSession.objects.filter(measured_at__gte=since).count(),
    }


def monitored_equipment():
    """Équipements suivis (au moins un point actif), avec le nombre de points et d'alertes actives."""
    from apps.assets.models import Equipment

    return (
        Equipment.objects.filter(measurement_points__is_active=True)
        .annotate(
            n_points=Count("measurement_points", filter=Q(measurement_points__is_active=True), distinct=True),
            n_alerts=Count("measurement_points__alerts", filter=~Q(measurement_points__alerts__status=Alert.Status.CLOSED), distinct=True),
        )
        .order_by("code")
    )


def search_points(query, limit):
    results = []
    for point in MeasurementPoint.objects.filter(
        Q(code__icontains=query) | Q(name__icontains=query) | Q(equipment__code__icontains=query)
    ).select_related("equipment")[:limit]:
        results.append(SearchResult(
            category=gettext("Points de mesure"), title=str(point), subtitle=point.position or point.code,
            url=point.get_absolute_url(), badge="", badge_class="",
        ))
    return results
