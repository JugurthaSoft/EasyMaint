"""Documents des interventions : fiche d'intervention PDF (avant ou après travaux) et export Excel des OT."""
import io

from django.apps import apps as django_apps
from django.utils import timezone
from django.utils.translation import gettext

from apps.core.formatting import format_money, format_number, smart_number
from apps.core.pdf import document


def _dt(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def _d(value):
    return value.strftime("%d/%m/%Y") if value else "—"


def work_order_pdf(wo, *, tenant, user):
    """Fiche d'intervention : à imprimer avant l'intervention (cases et lignes à remplir) ou comme compte rendu."""
    money = lambda value: format_money(value, tenant.currency_code, tenant.currency_decimals)  # noqa: E731
    equipment = wo.equipment
    technicians = ", ".join(str(t) for t in wo.technicians.all()) or "—"
    sections = [{
        "title": gettext("Intervention"),
        "kv": [
            (gettext("Équipement"), f"{equipment.code} · {equipment.designation}"), (gettext("Localisation"), equipment.location.full_path),
            (gettext("Type"), wo.get_kind_display()), (gettext("Priorité"), wo.get_priority_display()),
            (gettext("Statut"), wo.get_status_display()), (gettext("Arrêt de production"), "oui" if wo.production_stopped else "non"),
            (gettext("Date prévue"), _d(wo.planned_date)), (gettext("Échéance"), _d(wo.due_date)),
            (gettext("Temps estimé"), f"{smart_number(wo.estimated_hours)} h" if wo.estimated_hours else "—"),
            (gettext("Équipe"), str(wo.team) if wo.team else "—"), (gettext("Techniciens"), technicians),
            (gettext("Sous-traitant"), str(wo.contractor) if wo.contractor else "—"),
            (gettext("Début réel"), _dt(wo.started_at)), (gettext("Fin réelle"), _dt(wo.finished_at)),
        ],
    }, {"title": gettext("Description de la demande"), "text": wo.description or wo.title}]
    if wo.preventive_plan_id:
        sections.append({"title": gettext("Instructions du plan préventif"), "text": "\n".join(filter(None, [wo.preventive_plan.operations, wo.preventive_plan.instructions]))})
    done = wo.status in ("done", "validated")
    sections.append({"title": gettext("Diagnostic"), "text": wo.diagnosis} if wo.diagnosis else {"title": gettext("Diagnostic"), "lines": 3})
    if wo.kind == "corrective":
        sections.append({"title": gettext("Défaillance"), "kv": [
            (gettext("Mode de défaillance"), str(wo.failure_mode) if wo.failure_mode else "________________"),
            (gettext("Cause"), str(wo.failure_cause) if wo.failure_cause else "________________"),
        ]})
    sections.append({"title": gettext("Travaux réalisés"), "text": wo.work_done} if wo.work_done else {"title": gettext("Travaux réalisés"), "lines": 6})
    checklist = list(wo.checklist.all())
    if checklist:
        sections.append({"title": gettext("Check-list"), "table": (
            [gettext("Fait"), gettext("Point de contrôle"), gettext("Commentaire")],
            [["[x]" if item.is_done else "[  ]", item.label, item.comment] for item in checklist], [0.7, 6, 3], 9)})
    parts = [[p.reference or "", p.designation, smart_number(p.quantity), gettext("hors magasin")] for p in wo.parts.all()]
    if django_apps.is_installed("apps.inventory"):
        for line in wo.stock_parts.select_related("item", "warehouse"):
            parts.append([line.item.reference, line.item.designation, smart_number(line.consumed if line.issued else line.quantity),
                          gettext("magasin %(code)s · %(status)s") % {"code": line.warehouse.code, "status": line.get_status_display().lower()}])
    if parts or done:
        sections.append({"title": gettext("Pièces"), "table": ([gettext("Référence"), gettext("Désignation"), gettext("Quantité"), gettext("Origine")], parts, [2, 5, 1, 2.4], 2)})
    else:
        sections.append({"title": gettext("Pièces utilisées"), "lines": 3})
    entries = list(wo.time_entries.select_related("technician"))
    if entries:
        sections.append({"title": gettext("Temps passés"), "table": (
            [gettext("Technicien"), gettext("Début"), gettext("Fin"), gettext("Heures")],
            [[str(e.technician), _dt(e.started_at), _dt(e.ended_at), format_number(e.hours, 2) + (gettext(" (HS)") if e.is_overtime else "")]
             for e in entries], [3, 2, 2, 1.2], 3)})
    else:
        sections.append({"title": gettext("Temps passés"), "lines": 2})
    expenses = list(wo.expenses.all())
    if expenses:
        sections.append({"title": gettext("Prestations et dépenses"), "table": (
            [gettext("Nature"), gettext("Libellé"), gettext("Fournisseur"), gettext("Montant")],
            [[e.get_nature_display(), e.label, e.supplier, money(e.amount)] for e in expenses], [1.6, 4, 2.2, 1.6], 3)})
    if wo.status == "validated" and user.has_capability("costs.view"):
        sections.append({"title": gettext("Coûts (figés à la validation)"), "kv": [
            (gettext("Main-d'œuvre"), money(wo.labour_cost)), (gettext("Pièces"), money(wo.parts_cost)),
            (gettext("Prestations externes"), money(wo.external_cost)), (gettext("Autres dépenses"), money(wo.other_cost)),
            (gettext("Total"), money(wo.total_cost)), (gettext("Validé le"), gettext("%(date)s par %(user)s") % {"date": _dt(wo.validated_at), "user": wo.validated_by or "—"}),
        ]})
    return document(
        company=tenant.name, title=gettext("Fiche d'intervention"), reference=wo.number, subtitle=wo.title,
        sections=sections, signatures=[gettext("Technicien"), gettext("Demandeur / production"), gettext("Responsable maintenance")],
        generated=gettext("édité le %(date)s") % {"date": f"{timezone.localtime():%d/%m/%Y %H:%M}"},
    )


def work_orders_xlsx(queryset):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = gettext("Interventions")
    headers = [gettext("N°"), gettext("Type"), gettext("Statut"), gettext("Priorité"), gettext("Équipement"), gettext("Désignation"), gettext("Intitulé"), gettext("Créé le"), gettext("Date prévue"), gettext("Échéance"),
               gettext("Début réel"), gettext("Fin réelle"), gettext("Arrêt de production"), gettext("Techniciens"), gettext("Temps estimé (h)"), gettext("Main-d'œuvre"), gettext("Pièces"),
               gettext("Prestations"), gettext("Autres"), gettext("Coût total")]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    naive = lambda value: timezone.localtime(value).replace(tzinfo=None) if value else None  # noqa: E731
    for wo in queryset:
        validated = wo.status == "validated"
        sheet.append([
            wo.number, wo.get_kind_display(), wo.get_status_display(), wo.get_priority_display(), wo.equipment.code,
            wo.equipment.designation, wo.title, naive(wo.created_at), wo.planned_date, wo.due_date, naive(wo.started_at),
            naive(wo.finished_at), "oui" if wo.production_stopped else "non", ", ".join(str(t) for t in wo.technicians.all()),
            wo.estimated_hours, *( [wo.labour_cost, wo.parts_cost, wo.external_cost, wo.other_cost, wo.total_cost] if validated else [None] * 5),
        ])
    for column, fmt in (("H", "DD/MM/YYYY HH:MM"), ("I", "DD/MM/YYYY"), ("J", "DD/MM/YYYY"), ("K", "DD/MM/YYYY HH:MM"), ("L", "DD/MM/YYYY HH:MM")):
        for cell in sheet[column][1:]:
            cell.number_format = fmt
    widths = [17, 13, 15, 10, 13, 30, 40, 16, 12, 12, 16, 16, 10, 26, 10, 12, 12, 12, 12, 12]
    for index, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
