"""Lectures du préventif : liste des plans, indicateurs, planning."""
from datetime import timedelta

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.search import SearchResult
from apps.workorders.models import WorkOrder

from .models import PreventivePlan
from .services import CLOSED_STATUSES, estimated_meter_date, projected_dates

REALIZED = (WorkOrder.Status.DONE, WorkOrder.Status.VALIDATED)


def plans_with_status(params=None):
    """Plans avec, pour chacun, l'OT en attente et l'échéance affichée."""
    params = params or {}
    queryset = PreventivePlan.objects.select_related("equipment", "meter", "team").order_by("code")
    if params.get("inactifs") != "1":
        queryset = queryset.filter(is_active=True)
    query = (params.get("q") or "").strip()
    if query:
        queryset = queryset.filter(
            Q(code__icontains=query) | Q(name__icontains=query) | Q(equipment__code__icontains=query)
            | Q(equipment__designation__icontains=query)
        )
    plans = list(queryset)
    pending = {}
    for wo in WorkOrder.objects.filter(preventive_plan__in=plans).exclude(status__in=CLOSED_STATUSES):
        pending[wo.preventive_plan_id] = wo
    today = timezone.localdate()
    rows = []
    for plan in plans:
        estimate = estimated_meter_date(plan, today) if plan.uses_meter else None
        dates = [d for d in (plan.next_due_date if plan.uses_calendar else None, estimate) if d]
        next_date = min(dates) if dates else None
        rows.append({
            "plan": plan, "pending": pending.get(plan.pk), "next_date": next_date,
            "late": next_date is not None and next_date < today and plan.is_active,
        })
    return rows


def compliance(days=30, today=None):
    """
    Indicateurs du préventif sur les `days` derniers jours (échéances d'origine comprises dans la période) :
    - taux de réalisation = OT préventifs réalisés (terminés ou validés) / OT préventifs échus ;
    - respect du planning = OT réalisés au plus tard à leur échéance d'origine / OT préventifs échus.
    Les OT annulés comptent comme non réalisés.
    """
    today = today or timezone.localdate()
    start = today - timedelta(days=days - 1)
    due = (
        WorkOrder.objects.filter(kind=WorkOrder.Kind.PREVENTIVE)
        .annotate(reference_due=Coalesce("original_due_date", "due_date"))
        .filter(reference_due__gte=start, reference_due__lte=today)
    )
    total = due.count()
    realized = 0
    on_time = 0
    for wo in due.only("status", "finished_at", "original_due_date", "due_date"):
        if wo.status in REALIZED:
            realized += 1
            reference = wo.original_due_date or wo.due_date
            if wo.finished_at and timezone.localtime(wo.finished_at).date() <= reference:
                on_time += 1
    return {
        "days": days, "due": total, "realized": realized, "on_time": on_time,
        "realization_rate": round(100 * realized / total) if total else None,
        "on_time_rate": round(100 * on_time / total) if total else None,
    }


def upcoming_preventive(days=7, today=None):
    today = today or timezone.localdate()
    return WorkOrder.objects.filter(
        kind=WorkOrder.Kind.PREVENTIVE, status__in=WorkOrder.OPEN_STATUSES, due_date__lte=today + timedelta(days=days),
    ).count()


def planning_items(start, end, *, team=None, technician=None):
    """
    Éléments du planning entre deux dates :
    - les OT (date prévue, à défaut échéance), y compris terminés pour garder la trace de la période ;
    - les échéances calendaires futures des plans, pas encore transformées en OT (« prévision »).
    """
    today = timezone.localdate()
    orders = (
        WorkOrder.objects.exclude(status=WorkOrder.Status.CANCELLED)
        .annotate(day=Coalesce("planned_date", "due_date"))
        .filter(day__gte=start, day__lte=end)
        .select_related("equipment", "team").prefetch_related("technicians")
    )
    if team:
        orders = orders.filter(team_id=team)
    if technician:
        orders = orders.filter(technicians__id=technician).distinct()
    items = [{
        "day": wo.day, "kind": "order", "wo": wo, "label": f"{wo.equipment.code} · {wo.title}",
        "css": "late" if wo.is_late else ("done" if wo.status in REALIZED else wo.kind),
    } for wo in orders]
    # Les éléments en retard d'avant la période apparaissent aussi, le jour même, pour ne pas être oubliés.
    if start <= today <= end:
        overdue = (
            WorkOrder.objects.filter(status__in=WorkOrder.OPEN_STATUSES)
            .annotate(day=Coalesce("planned_date", "due_date")).filter(day__lt=start, due_date__lt=today)
            .select_related("equipment")
        )
        if team:
            overdue = overdue.filter(team_id=team)
        if technician:
            overdue = overdue.filter(technicians__id=technician).distinct()
        items += [{"day": today, "kind": "order", "wo": wo, "label": f"{wo.equipment.code} · {wo.title}", "css": "late"} for wo in overdue]
    plans = PreventivePlan.objects.filter(is_active=True).select_related("equipment")
    if team:
        plans = plans.filter(team_id=team)
    if technician:
        plans = plans.filter(technicians__id=technician).distinct()
    for plan in plans:
        for day in projected_dates(plan, max(start, today + timedelta(days=1)), end):
            items.append({"day": day, "kind": "forecast", "plan": plan, "label": f"{plan.equipment.code} · {plan.name}", "css": "forecast"})
    items.sort(key=lambda item: (item["day"], item["kind"] != "order", item["label"]))
    return items


def search_plans(query, limit):
    results = []
    for plan in PreventivePlan.objects.filter(
        Q(code__icontains=query) | Q(name__icontains=query) | Q(equipment__code__icontains=query)
    ).select_related("equipment")[:limit]:
        results.append(SearchResult(
            category=gettext("Plans préventifs"), title=str(plan), subtitle=f"{plan.equipment.code} · {plan.trigger_summary}",
            url=plan.get_absolute_url(), badge=gettext("Actif") if plan.is_active else gettext("Inactif"),
            badge_class="b-blue" if plan.is_active else "b-gray",
        ))
    return results
