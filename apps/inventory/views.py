import io

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext, gettext_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
    View,
)

from apps.accounts.permissions import CapabilityRequiredMixin, require_capability
from apps.assets.models import Equipment
from apps.core.mixins import AuditedFormMixin
from apps.core.models import AuditLog
from apps.core.services import log_action
from apps.workorders import services as wo_services
from apps.workorders.models import WorkOrder

from . import selectors, services
from .forms import (
    MOVEMENT_FORMS,
    BinForm,
    CountStartForm,
    EquipmentPartForm,
    FamilyForm,
    ItemForm,
    ItemSupplierForm,
    OrderReceiptForm,
    PartRequestForm,
    PurchaseRequestForm,
    QuantityForm,
    SupplierForm,
    WarehouseForm,
    find_item,
    parse_rows,
    to_decimal,
)
from .models import (
    EquipmentPart,
    Item,
    ItemSupplier,
    PartFamily,
    PurchaseRequest,
    StockCount,
    StockLevel,
    StockMovement,
    Supplier,
    Warehouse,
    WorkOrderPart,
)


def _tenant_user(request):
    if not request.user.is_authenticated or request.user.tenant_id is None:
        raise PermissionDenied


def _errors(request, form):
    for errors in form.errors.values():
        messages.error(request, " ".join(str(e) for e in errors))


def _back(request, default):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect(default)


def _run(request, action, success=""):
    try:
        result = action()
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return None
    if success:
        messages.success(request, success)
    return result


def _xlsx_response(workbook, filename):
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}-{timezone.localdate():%Y%m%d}.xlsx"'
    return response


def _sheet(title, headers, widths):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
    sheet.freeze_panes = "A2"
    return workbook, sheet


# --- Articles -----------------------------------------------------------------------------------

class ItemListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/item_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        return selectors.filter_items(self.request.GET)

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["inventory/_item_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context.update({
            "families": PartFamily.objects.order_by("name"),
            "states": selectors.STATES,
            "filters": self.request.GET,
            "filter_query": params.urlencode(),
            "data": selectors.overview(),
        })
        return context


class ItemExportView(CapabilityRequiredMixin, View):
    required_capability = "inventory.view"

    def get(self, request, *args, **kwargs):
        workbook, sheet = _sheet(gettext("Articles"), [
            gettext("Référence"), gettext("Désignation"), gettext("Famille"), gettext("Marque"), gettext("Réf. constructeur"), gettext("Unité"), gettext("Stock physique"), gettext("Réservé"),
            gettext("Disponible"), gettext("Stock mini"), gettext("Stock maxi"), "CMP", gettext("Valeur"), gettext("Critique"), gettext("Délai (j)"),
        ], [16, 40, 20, 14, 18, 10, 12, 10, 12, 10, 10, 12, 14, 9, 9])
        for item in selectors.filter_items(request.GET).select_related("family"):
            sheet.append([
                item.reference, item.designation, str(item.family or ""), item.brand, item.manufacturer_reference,
                item.get_unit_display(), item.physical, item.reserved, item.available, item.min_stock, item.max_stock,
                item.average_cost, item.stock_value, "oui" if item.is_critical else "", item.lead_time_days,
            ])
        log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Liste des articles (Excel)"]})
        return _xlsx_response(workbook, "articles")


class _ItemForm(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "inventory.manage"
    model = Item
    form_class = ItemForm
    template_name = "inventory/item_form.html"

    def get_success_url(self):
        return self.object.get_absolute_url()


class ItemCreateView(_ItemForm, CreateView):
    success_message = gettext_lazy("Article « %(name)s » créé.")


class ItemUpdateView(_ItemForm, UpdateView):
    success_message = gettext_lazy("Article « %(name)s » enregistré.")


class ItemDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "inventory.view"
    template_name = "inventory/item_detail.html"
    context_object_name = "item"

    def get_queryset(self):
        return selectors.items_with_stock().select_related("manufacturer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = self.object
        levels = list(StockLevel.objects.filter(item=item).select_related("warehouse").order_by("warehouse__code"))
        for level in levels:
            level.reserved = services.reserved_quantity(item, level.warehouse)
            level.available = level.quantity - level.reserved
        context.update({
            "levels": levels,
            "requests": item.requests.filter(status__in=WorkOrderPart.OPEN_STATUSES).select_related("work_order", "warehouse"),
            "movements": item.movements.select_related("warehouse", "work_order", "created_by", "supplier")[:40],
            "consumption": selectors.consumption(item),
            "suppliers": item.suppliers.select_related("supplier"),
            "supplier_form": ItemSupplierForm(item=item),
            "bin_form": BinForm(),
            "used_on": item.equipment_links.select_related("equipment").order_by("equipment__code"),
            "movement_kinds": [(key, label) for key, (_form, label) in MOVEMENT_FORMS.items()],
            "prices": list(services.price_history(item)[:30]),
        })
        chronological = list(reversed(context["prices"]))
        context["price_series"] = {
            "labels": [timezone.localtime(m.moved_at).strftime("%d/%m/%Y") for m in chronological],
            "values": [float(m.unit_cost) for m in chronological],
            "suppliers": [str(m.supplier or "—") for m in chronological],
        }
        return context


def _item_file(request, pk, field):
    _tenant_user(request)
    require_capability(request.user, "inventory.view")
    item = get_object_or_404(Item, pk=pk)
    file = getattr(item, field)
    if not file:
        raise Http404
    return FileResponse(file.open("rb"), as_attachment=field == "datasheet", filename=file.name.rsplit("/", 1)[-1])


@login_required
def item_photo(request, pk):
    return _item_file(request, pk, "photo")


@login_required
def item_datasheet(request, pk):
    return _item_file(request, pk, "datasheet")


@login_required
@require_POST
def item_supplier_add(request, pk):
    _tenant_user(request)
    require_capability(request.user, "inventory.manage")
    item = get_object_or_404(Item, pk=pk)
    form = ItemSupplierForm(request.POST, item=item)
    if form.is_valid():
        link = form.save(commit=False)
        link.item, link.created_by = item, request.user
        if link.is_preferred:
            item.suppliers.update(is_preferred=False)
        link.save()
        log_action(AuditLog.Action.UPDATE, request=request, obj=item, changes={_("Fournisseur"): ["", str(link.supplier)]})
        messages.success(request, _("Fournisseur ajouté."))
    else:
        _errors(request, form)
    return redirect(item)


@login_required
@require_POST
def item_supplier_delete(request, pk, link_pk):
    _tenant_user(request)
    require_capability(request.user, "inventory.manage")
    item = get_object_or_404(Item, pk=pk)
    link = get_object_or_404(ItemSupplier, pk=link_pk, item=item)
    log_action(AuditLog.Action.UPDATE, request=request, obj=item, changes={_("Fournisseur"): [str(link.supplier), ""]})
    link.delete()
    messages.success(request, _("Fournisseur retiré."))
    return redirect(item)


@login_required
@require_POST
def item_bin(request, pk):
    """Emplacement de l'article dans un magasin."""
    _tenant_user(request)
    if not (request.user.has_capability("stock.move") or request.user.has_capability("inventory.manage")):
        raise PermissionDenied
    item = get_object_or_404(Item, pk=pk)
    form = BinForm(request.POST)
    if form.is_valid():
        level, _created = StockLevel.objects.get_or_create(item=item, warehouse=form.cleaned_data["warehouse"])
        old = level.bin_location
        level.bin_location = form.cleaned_data["bin_location"].strip()
        level.save(update_fields=["bin_location", "updated_at"])
        log_action(AuditLog.Action.UPDATE, request=request, obj=item,
                   changes={_("Emplacement %(w)s") % {"w": level.warehouse.code}: [old, level.bin_location]})
        messages.success(request, _("Emplacement enregistré."))
    else:
        _errors(request, form)
    return redirect(item)


# --- Mouvements ---------------------------------------------------------------------------------

class MovementCreateView(CapabilityRequiredMixin, FormView):
    required_capability = "stock.move"
    template_name = "inventory/movement_form.html"

    def dispatch(self, request, *args, **kwargs):
        if kwargs["kind"] not in MOVEMENT_FORMS:
            raise Http404
        self.kind = kwargs["kind"]
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return MOVEMENT_FORMS[self.kind][0]

    def get_initial(self):
        initial = super().get_initial()
        item_pk = self.request.GET.get("article")
        if item_pk and item_pk.isdigit():
            item = Item.objects.filter(pk=int(item_pk)).first()
            if item is not None:
                initial["item"] = item.reference
                if self.kind == "entree":
                    initial["unit_cost"] = item.valuation_cost.quantize(services.Q3)
        warehouse = Warehouse.objects.filter(is_active=True).order_by("code").first()
        if warehouse is not None:
            initial.setdefault("warehouse", warehouse.pk)
            initial.setdefault("source", warehouse.pk)
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"kind": self.kind, "page_title": MOVEMENT_FORMS[self.kind][1], "kinds": MOVEMENT_FORMS.items()})
        return context

    def form_valid(self, form):
        data, user = form.cleaned_data, self.request.user
        actions = {
            "entree": lambda: services.receive(item=data["item"], warehouse=data["warehouse"], quantity=data["quantity"],
                                               unit_cost=data["unit_cost"], user=user, document=data["document"],
                                               reason=data["reason"], supplier=data["supplier"],
                                               purchase_order=data["purchase_order"]),
            "sortie": lambda: services.issue(item=data["item"], warehouse=data["warehouse"], quantity=data["quantity"], user=user,
                                             reason=data["reason"], document=data["document"], equipment=data["equipment"]),
            "transfert": lambda: services.transfer(item=data["item"], source=data["source"], destination=data["destination"],
                                                   quantity=data["quantity"], user=user, reason=data["reason"]),
            "ajustement": lambda: services.adjust(item=data["item"], warehouse=data["warehouse"], new_quantity=data["new_quantity"],
                                                  user=user, reason=data["reason"]),
        }
        try:
            movement = actions[self.kind]()
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, _("Mouvement %(n)s enregistré : %(ref)s, stock %(w)s = %(q)s.") % {
            "n": movement.number, "ref": movement.item.reference, "w": movement.warehouse.code, "q": services.fmt(movement.stock_after),
        })
        if movement.kind in SLIP_KINDS:
            _slip_message(self.request, movement)
        if self.request.POST.get("again"):
            return redirect(reverse("inventory:movement_create", args=[self.kind]))
        return redirect(movement.item)


class MovementListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/movement_list.html"
    context_object_name = "movements"
    paginate_by = 50

    def get_queryset(self):
        return selectors.filter_movements(self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context.update({
            "kinds": StockMovement.Kind.choices, "warehouses": Warehouse.objects.order_by("code"),
            "filters": self.request.GET, "filter_query": params.urlencode(),
        })
        return context


class MovementExportView(CapabilityRequiredMixin, View):
    required_capability = "inventory.view"

    def get(self, request, *args, **kwargs):
        workbook, sheet = _sheet(gettext("Mouvements"), [
            gettext("Date"), gettext("Numéro"), gettext("Type"), gettext("Référence"), gettext("Désignation"), gettext("Magasin"), gettext("Quantité"), gettext("Coût unitaire"), gettext("Valeur"),
            gettext("Stock après"), "OT", gettext("Document"), gettext("Motif"), gettext("Utilisateur"),
        ], [17, 18, 18, 16, 36, 10, 10, 12, 12, 11, 18, 18, 30, 16])
        for m in selectors.filter_movements(request.GET)[:20000]:
            sheet.append([
                timezone.localtime(m.moved_at).replace(tzinfo=None), m.number, m.get_kind_display(), m.item.reference,
                m.item.designation, m.warehouse.code, m.quantity, m.unit_cost, m.value, m.stock_after,
                m.work_order.number if m.work_order else "", m.document, m.reason, str(m.created_by or gettext("système")),
            ])
        for row in sheet.iter_rows(min_row=2, max_col=1):
            for cell in row:
                cell.number_format = "DD/MM/YYYY HH:MM"
        log_action(AuditLog.Action.EXPORT, request=request, changes={"Export": ["", "Mouvements de stock (Excel)"]})
        return _xlsx_response(workbook, "mouvements-stock")


# --- Pièces demandées pour les OT ------------------------------------------------------------------

class RequestQueueView(CapabilityRequiredMixin, ListView):
    """File des pièces à délivrer (écran du magasinier)."""

    required_capability = "inventory.view"
    template_name = "inventory/request_queue.html"
    context_object_name = "lines"

    def get_queryset(self):
        return selectors.open_requests()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for line in context["lines"]:
            line.in_stock = services.physical_quantity(line.item, line.warehouse)
        # Pièces délivrées sur des OT non validés : le retour se fait ici, sans accès à l'OT.
        context["returnable"] = (
            WorkOrderPart.objects.filter(issued__gt=F("returned")).exclude(work_order__status=WorkOrder.Status.VALIDATED)
            .select_related("item", "warehouse", "work_order", "work_order__equipment").order_by("-updated_at")[:40]
        )
        _attach_last_issue(context["returnable"])
        return context


def _slip_message(request, movement):
    """Lien vers le bon à faire signer, en message persistant (non refermé automatiquement)."""
    if movement is not None:
        label = _("Imprimer le bon de sortie à faire signer") if movement.kind == StockMovement.Kind.ISSUE else _(
            "Imprimer le bon de retour à faire signer")
        messages.info(request, format_html('<a class="fw-semibold" href="{}" target="_blank" rel="noopener">{}</a>',
                                           reverse("inventory:movement_slip", args=[movement.pk]), label))


SLIP_KINDS = (StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN)


def slip_group(movement):
    """
    Mouvements repris sur un même bon : même OT, même type, même jour, même magasinier et même
    magasin. Une sortie hors OT a son propre bon.
    """
    if movement.work_order_id is None:
        return [movement]
    day = timezone.localtime(movement.moved_at).date()
    return list(
        StockMovement.objects.filter(
            work_order_id=movement.work_order_id, kind=movement.kind, warehouse_id=movement.warehouse_id,
            created_by_id=movement.created_by_id, moved_at__date=day,
        ).select_related("item", "warehouse", "created_by").order_by("moved_at", "pk")
    )


@login_required
def movement_slip(request, pk):
    """Bon de sortie ou de retour à imprimer, signé par le magasinier et par le technicien."""
    _tenant_user(request)
    require_capability(request.user, "inventory.view")
    movement = get_object_or_404(
        StockMovement.objects.select_related("work_order", "work_order__equipment", "equipment", "warehouse", "created_by"),
        pk=pk, kind__in=SLIP_KINDS,
    )
    lines = slip_group(movement)
    bins = dict(StockLevel.objects.filter(warehouse=movement.warehouse, item__in=[m.item_id for m in lines])
                .values_list("item_id", "bin_location"))
    for line in lines:
        line.bin_location = bins.get(line.item_id, "")
        line.abs_quantity = abs(line.quantity)
    work_order = movement.work_order
    log_action(AuditLog.Action.EXPORT, request=request, obj=movement, changes={"Export": ["", _("Bon imprimé")]})
    return render(request, "inventory/slip.html", {
        "movement": movement, "lines": lines, "work_order": work_order,
        "equipment": work_order.equipment if work_order else movement.equipment,
        "technicians": list(work_order.technicians.all()) if work_order else [],
        "is_issue": movement.kind == StockMovement.Kind.ISSUE,
        "printed_at": timezone.localtime(),
    })


def _line(request, pk):
    _tenant_user(request)
    return get_object_or_404(WorkOrderPart.objects.select_related("work_order", "item", "warehouse"), pk=pk)


@login_required
@require_POST
def request_issue(request, pk):
    line = _line(request, pk)
    require_capability(request.user, "stock.move")
    form = QuantityForm(request.POST)
    if form.is_valid():
        movement = _run(request, lambda: services.issue_request(line, quantity=form.cleaned_data["quantity"], user=request.user),
                        success=_("%(ref)s délivré pour %(ot)s.") % {"ref": line.item.reference, "ot": line.work_order.number})
        _slip_message(request, movement)
    else:
        _errors(request, form)
    return _back(request, reverse("inventory:request_queue"))


@login_required
@require_POST
def request_return(request, pk):
    line = _line(request, pk)
    require_capability(request.user, "stock.move")
    form = QuantityForm(request.POST)
    if form.is_valid():
        movement = _run(request, lambda: services.return_request(line, quantity=form.cleaned_data["quantity"], user=request.user,
                                                                 reason=form.cleaned_data["reason"]),
                        success=_("Retour enregistré."))
        _slip_message(request, movement)
    else:
        _errors(request, form)
    return _back(request, reverse("inventory:request_queue"))


@login_required
@require_POST
def request_cancel(request, pk):
    line = _line(request, pk)
    if not request.user.has_capability("stock.move"):
        try:
            wo_services.ensure_editable(line.work_order, request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return _back(request, line.work_order.get_absolute_url())
    _run(request, lambda: services.cancel_request(line, user=request.user), success=_("Demande annulée : la réservation est libérée."))
    return _back(request, line.work_order.get_absolute_url())


@login_required
@require_POST
def wo_request_part(request, pk):
    """Demande d'une pièce du magasin depuis l'OT (technicien affecté ou responsable)."""
    _tenant_user(request)
    work_order = get_object_or_404(WorkOrder, pk=pk)
    try:
        wo_services.ensure_editable(work_order, request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return _back(request, work_order.get_absolute_url())
    form = PartRequestForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        line = _run(request, lambda: services.request_part(work_order=work_order, item=data["item"], quantity=data["quantity"],
                                                           warehouse=data["warehouse"], note=data["note"], user=request.user))
        if line is not None:
            available = services.available_quantity(line.item, line.warehouse)
            if available < 0:
                messages.warning(request, _("Pièce demandée, mais le stock du magasin %(w)s ne suffit pas : le magasin est prévenu.") % {
                    "w": line.warehouse.code})
            else:
                messages.success(request, _("Pièce demandée au magasin %(w)s : elle vous est réservée.") % {"w": line.warehouse.code})
    else:
        _errors(request, form)
    return _back(request, work_order.get_absolute_url())


def _attach_last_issue(lines):
    """Dernière délivrance de chaque ligne, pour le lien vers son bon de sortie."""
    lines = list(lines)
    last = {}
    for movement in StockMovement.objects.filter(request_line__in=lines, kind=StockMovement.Kind.ISSUE).order_by("pk"):
        last[movement.request_line_id] = movement
    for line in lines:
        line.last_issue = last.get(line.pk)
    return lines


def work_order_context(request, work_order):
    """Bloc « Pièces du magasin » de la fiche OT et de l'écran technicien."""
    lines = _attach_last_issue(work_order.stock_parts.select_related("item", "warehouse", "created_by"))
    can_request = wo_services._can_execute(request.user, work_order) and work_order.is_open
    return {
        "stock_parts": lines,
        "stock_part_form": PartRequestForm() if can_request else None,
        "can_request_parts": can_request,
        "can_issue_parts": request.user.has_capability("stock.move"),
        "stock_parts_value": sum((line.issued_value for line in lines), services.ZERO),
        "show_stock_parts": True,
    }


# --- Inventaires ----------------------------------------------------------------------------------

class CountListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/count_list.html"
    context_object_name = "counts"
    paginate_by = 30

    def get_queryset(self):
        return StockCount.objects.select_related("warehouse", "family", "validated_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or CountStartForm()
        return context

    def post(self, request):
        require_capability(request.user, "stock.count")
        form = CountStartForm(request.POST)
        if form.is_valid():
            count = _run(request, lambda: services.start_count(warehouse=form.cleaned_data["warehouse"], family=form.cleaned_data["family"],
                                                               notes=form.cleaned_data["notes"], user=request.user))
            if count is not None:
                messages.success(request, _("Inventaire %(n)s ouvert : saisissez les quantités comptées.") % {"n": count.number})
                return redirect(count)
        self.object_list = self.get_queryset()
        return self.render_to_response(self.get_context_data(form=form))


class CountDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "inventory.view"
    template_name = "inventory/count_detail.html"
    context_object_name = "count"

    def get_queryset(self):
        return StockCount.objects.select_related("warehouse", "family", "validated_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lines = list(self.object.lines.select_related("item"))
        context.update({
            "lines": lines,
            "counted": sum(1 for line in lines if line.counted is not None),
            "differences": sum(1 for line in lines if line.difference not in (None, 0)),
            "can_count": self.request.user.has_capability("stock.count") and self.object.status == StockCount.Status.OPEN,
        })
        return context

    def post(self, request, pk):
        require_capability(request.user, "stock.count")
        count = get_object_or_404(StockCount, pk=pk)
        values = {int(key[2:]): value for key, value in request.POST.items() if key.startswith("c-") and key[2:].isdigit()}
        if _run(request, lambda: services.save_counts(count, values) or True, success=_("Quantités enregistrées.")):
            if request.POST.get("then") == "validate":
                _run(request, lambda: services.validate_count(count, user=request.user),
                     success=_("Inventaire validé : les écarts sont enregistrés en mouvements de stock."))
        return redirect(count)


@login_required
@require_POST
def count_add_line(request, pk):
    _tenant_user(request)
    require_capability(request.user, "stock.count")
    count = get_object_or_404(StockCount, pk=pk)
    form = EquipmentPartForm({"item": request.POST.get("item", ""), "quantity": "1"})
    if form.is_valid():
        _run(request, lambda: services.add_count_line(count, item=form.cleaned_data["item"], user=request.user),
             success=_("Article ajouté à l'inventaire."))
    else:
        _errors(request, form)
    return redirect(count)


@login_required
@require_POST
def count_cancel(request, pk):
    _tenant_user(request)
    require_capability(request.user, "stock.count")
    count = get_object_or_404(StockCount, pk=pk)
    _run(request, lambda: services.cancel_count(count, user=request.user), success=_("Inventaire annulé."))
    return redirect("inventory:count_list")


@login_required
def count_export(request, pk):
    """Feuille de comptage à imprimer ou à remplir dans Excel."""
    _tenant_user(request)
    require_capability(request.user, "inventory.view")
    count = get_object_or_404(StockCount, pk=pk)
    levels = {level.item_id: level.bin_location for level in StockLevel.objects.filter(warehouse=count.warehouse)}
    workbook, sheet = _sheet(count.number, [gettext("Emplacement"), gettext("Référence"), gettext("Désignation"), gettext("Unité"), gettext("Stock théorique"), gettext("Quantité comptée")],
                             [14, 18, 44, 10, 14, 16])
    for line in count.lines.select_related("item"):
        sheet.append([levels.get(line.item_id, ""), line.item.reference, line.item.designation, line.item.get_unit_display(),
                      line.expected, line.counted])
    return _xlsx_response(workbook, f"inventaire-{count.number}")


# --- Référentiels : familles, magasins, fournisseurs ------------------------------------------------

class _SimpleForm(AuditedFormMixin, CapabilityRequiredMixin):
    required_capability = "inventory.manage"
    template_name = "assets/simple_form.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "page_title": self.page_title, "back_url_name": self.back_url_name}

    def get_success_url(self):
        return reverse(self.back_url_name)


class FamilyListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/family_list.html"
    context_object_name = "families"

    def get_queryset(self):
        from django.db.models import Count

        return PartFamily.objects.annotate(item_count=Count("items")).order_by("name")


class FamilyCreateView(_SimpleForm, CreateView):
    model, form_class, back_url_name = PartFamily, FamilyForm, "inventory:family_list"
    page_title = gettext_lazy("Nouvelle famille d'articles")
    success_message = gettext_lazy("Famille « %(name)s » créée.")


class FamilyUpdateView(_SimpleForm, UpdateView):
    model, form_class, back_url_name = PartFamily, FamilyForm, "inventory:family_list"
    page_title = gettext_lazy("Modifier la famille")
    success_message = gettext_lazy("Famille « %(name)s » enregistrée.")


class WarehouseListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/warehouse_list.html"
    context_object_name = "warehouses"

    def get_queryset(self):
        return Warehouse.objects.select_related("location").order_by("code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for warehouse in context["warehouses"]:
            warehouse.value = sum(
                (level.quantity * level.item.average_cost for level in warehouse.stock_levels.select_related("item")), services.ZERO,
            )
            warehouse.item_count = warehouse.stock_levels.filter(quantity__gt=0).count()
        return context


class WarehouseCreateView(_SimpleForm, CreateView):
    model, form_class, back_url_name = Warehouse, WarehouseForm, "inventory:warehouse_list"
    page_title = gettext_lazy("Nouveau magasin")
    success_message = gettext_lazy("Magasin « %(name)s » créé.")


class WarehouseUpdateView(_SimpleForm, UpdateView):
    model, form_class, back_url_name = Warehouse, WarehouseForm, "inventory:warehouse_list"
    page_title = gettext_lazy("Modifier le magasin")
    success_message = gettext_lazy("Magasin « %(name)s » enregistré.")


class SupplierListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/supplier_list.html"
    context_object_name = "suppliers"

    def get_queryset(self):
        from django.db.models import Count, Q

        suppliers = Supplier.objects.annotate(item_count=Count("items"))
        query = (self.request.GET.get("q") or "").strip()
        if query:
            suppliers = suppliers.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(contact_name__icontains=query))
        return suppliers.order_by("-is_active", "name")


class SupplierCreateView(_SimpleForm, CreateView):
    model, form_class, back_url_name = Supplier, SupplierForm, "inventory:supplier_list"
    page_title = gettext_lazy("Nouveau fournisseur")
    success_message = gettext_lazy("Fournisseur « %(name)s » créé.")

    def get_success_url(self):
        return self.object.get_absolute_url()


class SupplierUpdateView(_SimpleForm, UpdateView):
    model, form_class, back_url_name = Supplier, SupplierForm, "inventory:supplier_list"
    page_title = gettext_lazy("Modifier le fournisseur")
    success_message = gettext_lazy("Fournisseur « %(name)s » enregistré.")

    def get_success_url(self):
        return self.object.get_absolute_url()


class SupplierDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "inventory.view"
    template_name = "inventory/supplier_detail.html"
    context_object_name = "supplier"

    def get_queryset(self):
        return Supplier.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["links"] = self.object.items.select_related("item").order_by("item__reference")
        context["receipts"] = StockMovement.objects.filter(supplier=self.object).select_related("item", "warehouse")[:30]
        return context


# --- Nomenclature des équipements ----------------------------------------------------------------

@login_required
@require_POST
def equipment_part_add(request, equipment_pk):
    _tenant_user(request)
    require_capability(request.user, "inventory.manage")
    equipment = get_object_or_404(Equipment, pk=equipment_pk)
    form = EquipmentPartForm(request.POST)
    target = f"{equipment.get_absolute_url()}?onglet=pieces"
    if form.is_valid():
        item = form.cleaned_data["item"]
        if EquipmentPart.objects.filter(equipment=equipment, item=item).exists():
            messages.error(request, _("Cet article figure déjà dans la nomenclature."))
        else:
            EquipmentPart.objects.create(equipment=equipment, item=item, quantity=form.cleaned_data["quantity"],
                                         position=form.cleaned_data["position"], created_by=request.user)
            log_action(AuditLog.Action.UPDATE, request=request, obj=equipment, changes={_("Nomenclature"): ["", item.reference]})
            messages.success(request, _("Pièce ajoutée à la nomenclature."))
    else:
        _errors(request, form)
    return redirect(target)


@login_required
@require_POST
def equipment_part_delete(request, pk):
    _tenant_user(request)
    require_capability(request.user, "inventory.manage")
    link = get_object_or_404(EquipmentPart.objects.select_related("equipment", "item"), pk=pk)
    log_action(AuditLog.Action.UPDATE, request=request, obj=link.equipment, changes={_("Nomenclature"): [link.item.reference, ""]})
    link.delete()
    messages.success(request, _("Pièce retirée de la nomenclature."))
    return redirect(f"{link.equipment.get_absolute_url()}?onglet=pieces")


def equipment_tab_context(request, equipment):
    """Onglet « Pièces » de la fiche équipement : nomenclature, disponibilité, consommations."""
    links = list(equipment.spare_parts.select_related("item", "item__family"))
    stock = {item.pk: item for item in selectors.items_with_stock(Item.objects.filter(pk__in=[link.item_id for link in links]))}
    for link in links:
        link.stock = stock.get(link.item_id)
    return {
        "bom": links,
        "bom_form": EquipmentPartForm() if request.user.has_capability("inventory.manage") else None,
        "equipment_consumption": (StockMovement.objects.filter(equipment=equipment, kind__in=[StockMovement.Kind.ISSUE, StockMovement.Kind.RETURN])
                                  .select_related("item", "work_order", "warehouse")[:30]),
        "equipment_open_parts": (WorkOrderPart.objects.filter(work_order__equipment=equipment, status__in=WorkOrderPart.OPEN_STATUSES)
                                 .select_related("item", "work_order", "warehouse")),
    }


# --- Entrée sur bon de commande ------------------------------------------------------------------

RECEIPT_ROWS = 8


def _row_count(value, default, maximum):
    value = str(value or "")
    return min(max(int(value), 1), maximum) if value.isdigit() else default


@login_required
def order_receipt(request):
    """Entrée en stock de toutes les lignes d'un bon de commande papier, aux prix du BC."""
    _tenant_user(request)
    require_capability(request.user, "stock.move")
    count = _row_count(request.GET.get("lignes"), RECEIPT_ROWS, 40)
    form = OrderReceiptForm(request.POST or None, initial={"warehouse": Warehouse.objects.filter(is_active=True).order_by("code").first()})
    row_errors, rows = [], []
    if request.method == "POST":
        count = _row_count(request.POST.get("rows"), RECEIPT_ROWS, 40)
        rows = parse_rows(request.POST, "l", count, ["item", "quantity", "unit_cost"])
        lines = []
        for number, values in rows:
            try:
                item = find_item(values["item"])
                quantity, cost = to_decimal(values["quantity"]), to_decimal(values["unit_cost"])
                if item is None or quantity is None or cost is None:
                    raise forms.ValidationError(_("article, quantité et prix unitaire sont obligatoires."))
                if quantity <= 0 or cost < 0:
                    raise forms.ValidationError(_("quantité positive et prix non négatif."))
                lines.append((item, quantity, cost))
            except forms.ValidationError as error:
                row_errors.append(_("Ligne %(n)s : %(e)s") % {"n": number, "e": " ".join(error.messages)})
        if not rows:
            row_errors.append(_("Saisissez au moins une ligne."))
        if form.is_valid() and not row_errors:
            data = form.cleaned_data
            try:
                movements = services.receive_order(supplier=data["supplier"], warehouse=data["warehouse"], lines=lines,
                                                   purchase_order=data["purchase_order"], delivery_note=data["delivery_note"],
                                                   user=request.user)
            except ValidationError as error:
                row_errors.extend(error.messages)
            else:
                messages.success(request, _("Bon de commande %(bc)s : %(n)s ligne(s) entrée(s) en stock (mouvement %(m)s). Prix fournisseur mis à jour.") % {
                    "bc": data["purchase_order"], "n": len(movements), "m": movements[0].number})
                return redirect(f"{reverse('inventory:movement_list')}?q={movements[0].number}")
    posted = {f"l-{number - 1}": values for number, values in rows}
    return render(request, "inventory/order_receipt.html", {
        "form": form, "row_errors": row_errors, "rows": [(index, posted.get(f"l-{index}", {})) for index in range(count)],
        "row_count": count,
    })


# --- Demandes d'achat ----------------------------------------------------------------------------

class PurchaseListView(CapabilityRequiredMixin, ListView):
    required_capability = "inventory.view"
    template_name = "inventory/purchase_list.html"
    context_object_name = "requests"
    paginate_by = 30

    def get_queryset(self):
        from django.db.models import Count, Q

        requests = PurchaseRequest.objects.select_related("supplier", "created_by", "work_order", "equipment").annotate(
            line_count=Count("lines"))
        query = (self.request.GET.get("q") or "").strip()
        if query:
            requests = requests.filter(
                Q(number__icontains=query) | Q(reason__icontains=query) | Q(supplier__name__icontains=query)
                | Q(lines__designation__icontains=query) | Q(lines__reference__icontains=query)
            ).distinct()
        return requests


PR_FIELDS = ["item", "reference", "designation", "quantity", "unit", "estimated_price"]
PR_ROWS = 6


def _purchase_lines(post, count):
    """Lignes de DA saisies ; un article du magasin complète référence, désignation, unité et prix."""
    lines, errors = [], []
    for number, values in parse_rows(post, "l", count, PR_FIELDS):
        try:
            item = find_item(values["item"], active_only=False)
            quantity, price = to_decimal(values["quantity"]), to_decimal(values["estimated_price"])
            designation = values["designation"] or (item.designation if item else "")
            if not designation:
                raise forms.ValidationError(_("désignation manquante."))
            if quantity is None or quantity <= 0:
                raise forms.ValidationError(_("quantité manquante."))
            if price is not None and price < 0:
                raise forms.ValidationError(_("prix négatif."))
            if item is not None and price is None:
                link = item.suppliers.filter(is_preferred=True).first()
                price = (link.price if link and link.price is not None else item.unit_price) or None
            lines.append({
                "item": item, "reference": (values["reference"] or (item.reference if item else ""))[:80],
                "designation": designation[:200], "quantity": quantity.quantize(services.Q3),
                "unit": (values["unit"] or (item.get_unit_display() if item else ""))[:20], "estimated_price": price,
            })
        except forms.ValidationError as error:
            errors.append(_("Ligne %(n)s : %(e)s") % {"n": number, "e": " ".join(error.messages)})
    return lines, errors


def _purchase_rows(purchase, post, count):
    if post is not None:
        posted = {}
        for index in range(count):
            posted[index] = {name: post.get(f"l-{index}-{name}", "") for name in PR_FIELDS}
        return [(index, posted[index]) for index in range(count)]
    existing = list(purchase.lines.select_related("item")) if purchase and purchase.pk else []
    rows = []
    for index in range(max(count, len(existing) + 2)):
        line = existing[index] if index < len(existing) else None
        rows.append((index, {
            "item": line.item.reference if line and line.item else "", "reference": line.reference if line else "",
            "designation": line.designation if line else "", "quantity": f"{line.quantity.normalize():f}" if line else "",
            "unit": line.unit if line else "",
            "estimated_price": f"{line.estimated_price.normalize():f}" if line and line.estimated_price is not None else "",
        }))
    return rows


@login_required
def purchase_edit(request, pk=None):
    _tenant_user(request)
    require_capability(request.user, "purchasing.request")
    purchase = get_object_or_404(PurchaseRequest, pk=pk) if pk else None
    initial = {}
    if purchase is None:
        for name in ("work_order", "equipment"):
            value = request.GET.get(name)
            if value and value.isdigit():
                initial[name] = int(value)
    form = PurchaseRequestForm(request.POST or None, instance=purchase, initial=initial)
    count = PR_ROWS
    errors = []
    if request.method == "POST":
        count = _row_count(request.POST.get("rows"), PR_ROWS, 60)
        lines, errors = _purchase_lines(request.POST, count)
        if not lines and not errors:
            errors.append(_("Ajoutez au moins une ligne à la demande d'achat."))
        if form.is_valid() and not errors:
            try:
                purchase = services.save_purchase_request(form.save(commit=False), lines, user=request.user)
            except ValidationError as error:
                errors.extend(error.messages)
            else:
                messages.success(request, _("Demande d'achat %(n)s enregistrée : imprimez-la pour signature.") % {"n": purchase.number})
                return redirect(purchase)
    else:
        count = _row_count(request.GET.get("lignes"), PR_ROWS, 60)
    return render(request, "inventory/purchase_form.html", {
        "form": form, "purchase": purchase, "errors": errors,
        "rows": _purchase_rows(purchase, request.POST if request.method == "POST" else None, count),
    })


class PurchaseDetailView(CapabilityRequiredMixin, DetailView):
    required_capability = "inventory.view"
    template_name = "inventory/purchase_detail.html"
    context_object_name = "purchase"

    def get_queryset(self):
        return PurchaseRequest.objects.select_related("supplier", "created_by", "work_order", "equipment")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["lines"] = list(self.object.lines.select_related("item"))
        context["total"] = sum((line.estimated_total for line in context["lines"]), services.ZERO)
        context["print_mode"] = self.request.GET.get("imprimer") == "1"
        if context["print_mode"]:
            log_action(AuditLog.Action.EXPORT, request=self.request, obj=self.object, changes={"Export": ["", _("Demande d'achat imprimée")]})
        return context


@login_required
@require_POST
def purchase_delete(request, pk):
    _tenant_user(request)
    require_capability(request.user, "purchasing.request")
    purchase = get_object_or_404(PurchaseRequest, pk=pk)
    log_action(AuditLog.Action.DELETE, request=request, obj=purchase, changes={_("Demande d'achat"): [purchase.number, ""]})
    purchase.delete()
    messages.success(request, _("Demande d'achat supprimée."))
    return redirect("inventory:purchase_list")


@login_required
def purchase_reorder(request):
    """Articles sous le minimum : quantités proposées, puis une DA par fournisseur principal."""
    _tenant_user(request)
    require_capability(request.user, "purchasing.request")
    items = list(selectors.below_minimum().prefetch_related("suppliers__supplier"))
    for item in items:
        item.proposed = services.reorder_quantity(item, item.available)
        link = next((link for link in item.suppliers.all() if link.is_preferred), None)
        item.preferred_supplier = link.supplier if link else None
    if request.method == "POST":
        selected = {int(pk) for pk in request.POST.getlist("item") if pk.isdigit()}
        chosen = [item for item in items if item.pk in selected and item.proposed > 0]
        if not chosen:
            messages.error(request, _("Cochez au moins un article."))
        else:
            created = services.create_reorder_requests(chosen, user=request.user)
            messages.success(request, _("%(n)s demande(s) d'achat préparée(s), une par fournisseur : vérifiez-les puis imprimez-les.") % {
                "n": len(created)})
            return redirect("inventory:purchase_list")
    return render(request, "inventory/purchase_reorder.html", {"items": items})
