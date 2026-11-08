"""Fiche équipement PDF : identification, compteurs et, selon les modules installés et les droits,
plans préventifs, points de mesure, nomenclature, historique des interventions et coûts."""
from django.apps import apps as django_apps
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.formatting import format_money, smart_number
from apps.core.pdf import document


def _d(value):
    return value.strftime("%d/%m/%Y") if value else "—"


def equipment_pdf(equipment, *, tenant, user):
    sections = [{
        "title": gettext("Identification"),
        "kv": [
            (gettext("Code"), equipment.code), (gettext("Désignation"), equipment.designation),
            (gettext("Famille"), str(equipment.family)), (gettext("Localisation"), equipment.location.full_path),
            (gettext("Fabricant"), str(equipment.manufacturer) if equipment.manufacturer else "—"), (gettext("Modèle"), equipment.model or "—"),
            (gettext("N° de série"), equipment.serial_number or "—"), (gettext("Mise en service"), _d(equipment.commissioning_date)),
            (gettext("État"), equipment.get_status_display()), (gettext("Criticité"), equipment.criticality),
            (gettext("Responsable"), str(equipment.responsible) if equipment.responsible else "—"),
            (gettext("Temps requis"), gettext("%(hours)s h/j · %(days)s j/7") % {"hours": smart_number(equipment.required_hours_per_day), "days": equipment.operating_days_per_week}),
            (gettext("Équipement parent"), str(equipment.parent) if equipment.parent else "—"),
            (gettext("Sous-équipements"), ", ".join(child.code for child in equipment.children.all()) or "—"),
        ],
    }]
    if equipment.notes:
        sections.append({"title": gettext("Notes"), "text": equipment.notes})
    meters = list(equipment.meters.all())
    if meters:
        sections.append({"title": gettext("Compteurs"), "table": (
            [gettext("Compteur"), gettext("Valeur"), gettext("Unité"), gettext("Dernier relevé")],
            [[m.name, smart_number(m.current_value), m.unit, _d(timezone.localtime(m.last_reading_at).date() if m.last_reading_at else None)]
             for m in meters], [4, 2, 1.4, 2], 1)})
    if django_apps.is_installed("apps.preventive") and user.has_capability("preventive.view"):
        plans = list(equipment.preventive_plans.filter(is_active=True))
        sections.append({"title": gettext("Plans préventifs"), "table": (
            [gettext("Code"), gettext("Opération"), gettext("Périodicité"), gettext("Prochaine échéance")],
            [[p.code, p.name, " / ".join(filter(None, [p.period_label, p.meter_label])), _d(p.next_due_date)] for p in plans],
            [1.6, 4.4, 2.6, 1.8], 9)})
    if django_apps.is_installed("apps.condition") and user.has_capability("condition.view"):
        points = list(equipment.measurement_points.filter(is_active=True).prefetch_related("parameters"))
        if points:
            sections.append({"title": gettext("Points de mesure"), "table": (
                [gettext("Point"), gettext("Nom"), gettext("Paramètres")],
                [[p.code, p.name, ", ".join(par.code for par in p.parameters.all())] for p in points], [1.4, 4, 5], 9)})
    if django_apps.is_installed("apps.inventory") and user.has_capability("inventory.view"):
        bom = list(equipment.spare_parts.select_related("item"))
        if bom:
            sections.append({"title": gettext("Pièces de rechange (nomenclature)"), "table": (
                [gettext("Référence"), gettext("Désignation"), gettext("Qté montée"), gettext("Repère")],
                [[b.item.reference, b.item.designation, smart_number(b.quantity), b.position] for b in bom], [2, 5, 1.2, 3], 2)})
    if user.has_capability("workorders.view"):
        orders = list(equipment.work_orders.order_by("-created_at")[:25])
        sections.append({"title": gettext("Dernières interventions"), "table": (
            [gettext("N°"), gettext("Date"), gettext("Type"), gettext("Intitulé"), gettext("Statut")],
            [[o.number, _d(timezone.localtime(o.finished_at or o.created_at).date()), o.get_kind_display(), o.title, o.get_status_display()]
             for o in orders], [2.2, 1.6, 1.6, 5, 1.6], 9)})
    if django_apps.is_installed("apps.finance") and user.has_capability("costs.view"):
        from apps.finance.selectors import equipment_history

        history = equipment_history(equipment)
        money = lambda value: format_money(value, tenant.currency_code, tenant.currency_decimals)  # noqa: E731
        rows = [[str(year), money(v["labour"]), money(v["parts"]), money(v["external"]), money(v["other"]), money(v["total"]), str(v["count"])]
                for year, v in history["years"]]
        if rows:
            total = history["total"]
            rows.append([gettext("Cumul"), money(total["labour"]), money(total["parts"]), money(total["external"]), money(total["other"]),
                         money(total["total"]), str(total["count"])])
        sections.append({"title": gettext("Coûts de maintenance"), "table": (
            [gettext("Année"), gettext("Main-d'œuvre"), gettext("Pièces"), gettext("Prestations"), gettext("Autres"), gettext("Total"), "OT"], rows, [1, 2, 2, 2, 2, 2.2, 0.8], 1)})
    return document(company=tenant.name, title=gettext("Fiche équipement"), reference=equipment.code, subtitle=equipment.designation,
                    sections=sections, generated=gettext("édité le %(date)s") % {"date": f"{timezone.localtime():%d/%m/%Y %H:%M}"})
