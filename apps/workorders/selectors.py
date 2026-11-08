"""Lectures des interventions (filtres, compteurs, recherche). Toujours limitées à l'entreprise courante."""
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from apps.core.search import SearchResult

from .models import WorkOrder, WorkRequest

OPEN = WorkOrder.OPEN_STATUSES

# Pastilles de filtre de la liste des OT : clé d'URL -> (libellé, filtre)
STATUS_FILTERS = {
    "ouverts": (gettext_lazy("Ouverts"), Q(status__in=OPEN)),
    "a-planifier": (gettext_lazy("À planifier"), Q(status=WorkOrder.Status.TO_PLAN)),
    "affectes": (gettext_lazy("Affectés"), Q(status=WorkOrder.Status.ASSIGNED)),
    "en-cours": (gettext_lazy("En cours"), Q(status=WorkOrder.Status.IN_PROGRESS)),
    "en-attente": (gettext_lazy("En attente"), Q(status__in=[WorkOrder.Status.WAITING_PARTS, WorkOrder.Status.WAITING_EXTERNAL])),
    "termines": (gettext_lazy("Terminés à valider"), Q(status=WorkOrder.Status.DONE)),
    "valides": (gettext_lazy("Validés"), Q(status=WorkOrder.Status.VALIDATED)),
    "annules": (gettext_lazy("Annulés"), Q(status=WorkOrder.Status.CANCELLED)),
    "tous": (gettext_lazy("Tous"), Q()),
}


def base_queryset():
    return WorkOrder.objects.select_related("equipment", "equipment__location", "team", "contractor").prefetch_related("technicians")


def _text_filter(query):
    return (
        Q(number__icontains=query) | Q(title__icontains=query) | Q(description__icontains=query)
        | Q(equipment__code__icontains=query) | Q(equipment__designation__icontains=query)
        | Q(technicians__last_name__icontains=query) | Q(technicians__first_name__icontains=query)
    )


def filter_work_orders(params, *, base=None):
    """Filtre la liste des OT : statut (pastille), texte, type, retard, équipement."""
    queryset = base if base is not None else base_queryset()
    key = params.get("statut") or "ouverts"
    queryset = queryset.filter(STATUS_FILTERS.get(key, STATUS_FILTERS["ouverts"])[1])
    query = (params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(_text_filter(query)).distinct()
    kind = params.get("type")
    if kind in WorkOrder.Kind.values:
        queryset = queryset.filter(kind=kind)
    if params.get("retard") == "1":
        queryset = queryset.filter(status__in=OPEN, due_date__lt=timezone.localdate())
    equipment = params.get("equipement")
    if equipment and str(equipment).isdigit():
        queryset = queryset.filter(equipment_id=int(equipment))
    return queryset.order_by("priority", "due_date", "-created_at")


def status_filter_counts(params):
    """Nombre d'OT par pastille, en tenant compte des autres filtres (texte, type, retard)."""
    others = {key: value for key, value in params.items() if key != "statut"}
    base = base_queryset()
    query = (others.get("q") or "").strip()
    if query:
        base = base.filter(_text_filter(query)).distinct()
    if others.get("type") in WorkOrder.Kind.values:
        base = base.filter(kind=others["type"])
    if others.get("retard") == "1":
        base = base.filter(status__in=OPEN, due_date__lt=timezone.localdate())
    return {key: base.filter(condition).count() for key, (_label, condition) in STATUS_FILTERS.items()}


def overview():
    """Chiffres du tableau de bord pour les interventions."""
    today = timezone.localdate()
    open_orders = WorkOrder.objects.filter(status__in=OPEN)
    return {
        "open": open_orders.count(),
        "in_progress": open_orders.filter(status=WorkOrder.Status.IN_PROGRESS).count(),
        "waiting": open_orders.filter(status__in=[WorkOrder.Status.WAITING_PARTS, WorkOrder.Status.WAITING_EXTERNAL]).count(),
        "late": open_orders.filter(due_date__lt=today).count(),
        "to_plan": open_orders.filter(status=WorkOrder.Status.TO_PLAN).count(),
        "to_validate": WorkOrder.objects.filter(status=WorkOrder.Status.DONE).count(),
        "new_requests": WorkRequest.objects.filter(status=WorkRequest.Status.NEW).count(),
        "backlog_hours": open_orders.aggregate(h=Sum("estimated_hours"))["h"] or 0,
    }


def late_work_orders(limit=6):
    return list(base_queryset().filter(status__in=OPEN, due_date__lt=timezone.localdate()).order_by("due_date")[:limit])


def equipment_history(equipment):
    """Interventions d'un équipement et coût cumulé des OT validés."""
    orders = base_queryset().filter(equipment=equipment).order_by("-created_at")
    totals = WorkOrder.objects.filter(equipment=equipment, status=WorkOrder.Status.VALIDATED).aggregate(
        total=Sum("total_cost"), count=Count("pk"),
    )
    failures = WorkOrder.objects.filter(equipment=equipment, kind=WorkOrder.Kind.CORRECTIVE).exclude(
        status=WorkOrder.Status.CANCELLED,
    ).count()
    return {"orders": orders[:50], "validated_cost": totals["total"] or 0, "validated_count": totals["count"], "failures": failures}


# --- Recherche globale -----------------------------------------------------------------

def search_work_orders(query, limit):
    results = []
    for wo in WorkOrder.objects.filter(
        Q(number__icontains=query) | Q(title__icontains=query) | Q(equipment__code__icontains=query)
    ).select_related("equipment").order_by("-created_at")[:limit]:
        results.append(SearchResult(
            category=gettext("Ordres de travail"), title=f"{wo.number} · {wo.title}", subtitle=str(wo.equipment),
            url=wo.get_absolute_url(), badge=wo.get_status_display(), badge_class=wo.status_badge,
        ))
    return results


def search_requests(query, limit):
    results = []
    for request_obj in WorkRequest.objects.filter(
        Q(number__icontains=query) | Q(description__icontains=query) | Q(equipment__code__icontains=query)
    ).select_related("equipment").order_by("-requested_at")[:limit]:
        results.append(SearchResult(
            category=gettext("Demandes d'intervention"), title=f"{request_obj.number} · {request_obj.equipment.code}",
            subtitle=request_obj.description[:90], url=request_obj.get_absolute_url(),
            badge=request_obj.get_status_display(), badge_class=request_obj.status_badge,
        ))
    return results
