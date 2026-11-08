"""
Blocs du tableau de bord d'accueil.

Chaque bloc déclare sa capacité, son gabarit, sa largeur et la fonction qui calcule ses données
(appelée seulement si le bloc est affiché). L'utilisateur choisit et ordonne ses blocs ; à défaut,
une présentation par rôle s'applique.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import selectors


@dataclass(frozen=True)
class Block:
    key: str
    label: str
    capability: str
    template: str
    width: str = "half"  # "full" ou "half"
    chart: bool = False
    app: str = ""
    technician_only: bool = False
    cached: bool = False  # données identiques pour toute l'entreprise : gardées en cache quelques minutes


def _interventions(request):
    from apps.workorders import selectors as wo

    return {"wo": wo.overview()}


def _late_orders(request):
    from apps.workorders import selectors as wo

    return {"late_orders": wo.late_work_orders(limit=8)}


def _my_work(request):
    from apps.workorders.models import WorkOrder

    technician = getattr(request.user, "technician", None)
    orders = []
    if technician is not None:
        orders = list(WorkOrder.objects.filter(technicians=technician, status__in=WorkOrder.OPEN_STATUSES)
                      .select_related("equipment").order_by("priority", "due_date", "pk")[:8])
    return {"my_orders": orders}


def _reliability(request):
    from apps.kpi import selectors as kpi

    end = timezone.localdate()
    start = end - timedelta(days=29)
    return {"reliability": kpi.reliability(kpi.scope(), start, end)}


def _reliability_trend(request):
    from apps.kpi import selectors as kpi

    rows = kpi.trend(end=timezone.localdate())
    return {"reliability_trend": {
        "labels": [row["label"] for row in rows], "failures": [row["failures"] for row in rows],
        "availability": [row["availability"] for row in rows], "mtbf": [row["mtbf"] for row in rows], "mttr": [row["mttr"] for row in rows],
    }}


def _top_failures(request):
    from apps.kpi import selectors as kpi

    end = timezone.localdate()
    items = kpi.scope()
    per_equipment = kpi.reliability_by_equipment(items, end - timedelta(days=364), end)
    names = {e.pk: e for e in items}
    rows = sorted(((names[pk], rel) for pk, rel in per_equipment.items() if rel.failures),
                  key=lambda row: (-row[1].failures, -row[1].downtime_failure))[:10]
    return {"top_failures": rows}


def _condition(request):
    from apps.condition import selectors as condition

    alerts = condition.sort_alerts(condition.active_alerts())
    return {"condition_alerts": alerts[:5], "condition_alert_count": len(alerts), "condition_card": True}


def _costs(request):
    from apps.finance import selectors as finance
    from apps.finance.models import Budget

    today = timezone.localdate()
    records = finance.cost_records(date(today.year, 1, 1), today)
    budget = sum((b.annual for b in Budget.objects.filter(year=today.year)), Decimal("0"))
    spent = sum((r.total for r in records), Decimal("0"))
    return {"finance": {
        "month": sum((r.total for r in records if r.day.month == today.month), Decimal("0")),
        "year": spent, "budget": budget, "rate": (spent / budget * 100) if budget else None,
    }}


def _top_costly(request):
    from apps.finance import selectors as finance

    today = timezone.localdate()
    return {"top_costly": finance.group(finance.cost_records(date(today.year, 1, 1), today), "equipement")[:10]}


def _stock(request):
    from apps.inventory import selectors as inventory

    return {"stock": inventory.overview(), "stock_card": True}


def _preventive(request):
    from apps.preventive import selectors as preventive

    return {"preventive": preventive.compliance(), "preventive_upcoming": preventive.upcoming_preventive()}


def _fleet(request):
    stale_count, _stale = selectors.stale_meters()
    return {"summary": selectors.equipment_summary(), "stale_count": stale_count, "stale_days": selectors.STALE_METER_DAYS}


def _fleet_chart(request):
    return {"by_workshop": selectors.equipment_by_workshop()}


def _broken(request):
    return {"broken_list": selectors.broken_equipment()}


def _stale(request):
    stale_count, stale_list = selectors.stale_meters()
    return {"stale_list": stale_list, "stale_count": stale_count, "stale_days": selectors.STALE_METER_DAYS}


def _recent(request):
    return {"recent_changes": selectors.recent_changes(request.tenant)}


BLOCKS = [
    (Block("my_work", _("Mes interventions"), "workorders.execute", "dashboard/blocks/my_work.html", technician_only=True), _my_work),
    (Block("interventions", _("Interventions : chiffres clés"), "workorders.view", "dashboard/blocks/interventions.html", "full"), _interventions),
    (Block("reliability", _("Fiabilité · 30 derniers jours (MTBF, MTTR, disponibilité)"), "kpi.view", "dashboard/blocks/reliability.html", "full", app="apps.kpi", cached=True), _reliability),
    (Block("condition_alerts", _("Alertes conditionnelles"), "condition.view", "dashboard/blocks/condition.html", app="apps.condition"), _condition),
    (Block("costs", _("Coûts du mois et de l'année"), "costs.view", "dashboard/blocks/costs.html", app="apps.finance", cached=True), _costs),
    (Block("stock", _("Stock sous le minimum"), "inventory.view", "dashboard/blocks/stock.html", app="apps.inventory"), _stock),
    (Block("preventive", _("Préventif : réalisation et planning"), "preventive.view", "dashboard/blocks/preventive.html", "full", app="apps.preventive"), _preventive),
    (Block("reliability_trend", _("Pannes, disponibilité, MTBF et MTTR · 12 mois"), "kpi.view", "dashboard/blocks/reliability_trend.html", chart=True, app="apps.kpi", cached=True), _reliability_trend),
    (Block("top_failures", _("Top 10 des équipements les plus défaillants · 12 mois"), "kpi.view", "dashboard/blocks/top_failures.html", app="apps.kpi", cached=True), _top_failures),
    (Block("top_costly", _("Top 10 des équipements les plus coûteux · année en cours"), "costs.view", "dashboard/blocks/top_costly.html", app="apps.finance", cached=True), _top_costly),
    (Block("late_orders", _("OT en retard"), "workorders.view", "dashboard/blocks/late_orders.html"), _late_orders),
    (Block("fleet", _("Situation du parc"), "assets.view", "dashboard/blocks/fleet.html", "full"), _fleet),
    (Block("fleet_chart", _("Équipements par unité et par état"), "assets.view", "dashboard/blocks/fleet_chart.html", chart=True), _fleet_chart),
    (Block("broken", _("Équipements en panne"), "assets.view", "dashboard/blocks/broken.html"), _broken),
    (Block("stale_meters", _("Compteurs sans relevé récent"), "assets.view", "dashboard/blocks/stale_meters.html"), _stale),
    (Block("recent_changes", _("Dernières modifications du patrimoine"), "assets.view", "dashboard/blocks/recent_changes.html"), _recent),
]
REGISTRY = {block.key: (block, provider) for block, provider in BLOCKS}

_MANAGER = ["interventions", "reliability", "condition_alerts", "costs", "stock", "preventive", "late_orders", "broken",
            "reliability_trend", "top_failures", "fleet", "fleet_chart", "top_costly", "stale_meters", "recent_changes"]
ROLE_DEFAULTS = {
    "admin": _MANAGER,
    "maintenance_manager": _MANAGER,
    "maintenance_engineer": ["reliability", "reliability_trend", "condition_alerts", "interventions", "top_failures", "preventive",
                             "late_orders", "broken", "stock", "costs", "top_costly", "stale_meters"],
    "team_leader": ["interventions", "late_orders", "my_work", "condition_alerts", "broken", "preventive", "reliability", "stale_meters"],
    "technician": ["my_work", "condition_alerts", "broken", "stale_meters", "preventive"],
    "storekeeper": ["stock", "broken", "reliability", "fleet"],
    "production_manager": ["fleet", "broken", "reliability", "reliability_trend", "interventions", "costs", "top_failures"],
    "management": ["reliability", "costs", "reliability_trend", "top_costly", "top_failures", "preventive", "fleet", "interventions"],
}


def _is_technician(user):
    technician = getattr(user, "technician", None) if hasattr(user, "technician") else None
    return technician is not None and technician.is_active


def available(user):
    """Blocs autorisés pour l'utilisateur, dans l'ordre du catalogue."""
    result = []
    for block, _provider in BLOCKS:
        if block.app and not django_apps.is_installed(block.app):
            continue
        if not user.has_capability(block.capability):
            continue
        if block.technician_only and not _is_technician(user):
            continue
        result.append(block)
    return result


def default_keys(user):
    role = getattr(getattr(user, "role", None), "code", "")
    allowed = [block.key for block in available(user)]
    preferred = ROLE_DEFAULTS.get(role)
    if not preferred:
        return allowed
    return [key for key in preferred if key in allowed]


def layout(user):
    """Clés des blocs à afficher, dans l'ordre : choix de l'utilisateur, sinon présentation de son rôle."""
    from .models import DashboardLayout

    allowed = {block.key for block in available(user)}
    saved = DashboardLayout.objects.filter(user=user).first()
    if saved is not None:
        return [key for key in saved.blocks if key in allowed], True
    return default_keys(user), False


def build(request, keys):
    """Blocs à afficher avec leurs données."""
    blocks, context = [], {}
    for key in keys:
        block, provider = REGISTRY[key]
        context.update(_data(block, provider, request))
        blocks.append(block)
    return blocks, context


def _data(block, provider, request):
    """Données d'un bloc ; les indicateurs communs à l'entreprise sont recalculés au plus toutes les N minutes."""
    seconds = settings.EASYMAINT_DASHBOARD_CACHE_SECONDS
    tenant = getattr(request, "tenant", None)
    if not block.cached or seconds <= 0 or tenant is None:
        return provider(request)
    cache_key = f"easymaint:dash:{tenant.pk}:{block.key}:{timezone.localdate():%Y%m%d}"
    data = cache.get(cache_key)
    if data is None:
        data = provider(request)
        cache.set(cache_key, data, seconds)
    return data
