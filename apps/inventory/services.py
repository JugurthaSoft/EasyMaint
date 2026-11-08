"""
Règles du stock.

- Tout changement de quantité passe par `_record()` : verrou sur l'article et la ligne de
  stock, refus du stock négatif, CMP recalculé aux entrées, mouvement définitif horodaté.
- Disponible = physique − réservé (pièces demandées pour des OT et pas encore délivrées).
  Les sorties hors OT et les transferts ne peuvent pas entamer le réservé ; la délivrance
  d'une pièce demandée consomme sa propre réservation.
- Les droits sont contrôlés dans les vues ; ces fonctions servent aussi au système
  (plans préventifs, démonstration).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import AuditLog
from apps.core.services import log_action, next_document_number

from .models import (
    Item,
    ItemSupplier,
    PurchaseRequest,
    PurchaseRequestLine,
    StockCount,
    StockCountLine,
    StockLevel,
    StockMovement,
    Warehouse,
    WorkOrderPart,
)

ZERO = Decimal("0")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
K = StockMovement.Kind


def _qty(value, field=_("Quantité")):
    try:
        value = Decimal(value)
    except Exception:
        raise ValidationError(_("%(f)s invalide.") % {"f": field}) from None
    return value.quantize(Q3, rounding=ROUND_HALF_UP)


def _positive(value):
    value = _qty(value)
    if value <= 0:
        raise ValidationError(_("La quantité doit être positive."))
    return value


def fmt(value):
    """Quantité lisible dans un message : 3 au lieu de 3.000."""
    value = Decimal(value).normalize()
    return format(value, "f").replace(".", ",")


# --- Lectures ------------------------------------------------------------------------------

def physical_quantity(item, warehouse=None):
    levels = StockLevel.objects.filter(item=item)
    if warehouse is not None:
        levels = levels.filter(warehouse=warehouse)
    return levels.aggregate(q=Sum("quantity"))["q"] or ZERO


def reserved_quantity(item, warehouse=None, *, exclude_line=None):
    lines = WorkOrderPart.objects.filter(item=item, status__in=WorkOrderPart.OPEN_STATUSES)
    if warehouse is not None:
        lines = lines.filter(warehouse=warehouse)
    if exclude_line is not None:
        lines = lines.exclude(pk=exclude_line.pk)
    remaining = ExpressionWrapper(F("quantity") - F("issued"), output_field=DecimalField(max_digits=12, decimal_places=3))
    return lines.aggregate(q=Sum(remaining))["q"] or ZERO


def available_quantity(item, warehouse=None):
    return physical_quantity(item, warehouse) - reserved_quantity(item, warehouse)


def work_order_parts_cost(work_order):
    """Valeur des pièces du magasin consommées par l'OT (délivrées − retournées), au CMP de sortie."""
    return WorkOrderPart.objects.filter(work_order=work_order).aggregate(v=Sum("issued_value"))["v"] or ZERO


# --- Mouvement élémentaire ------------------------------------------------------------------

def _lock(item, warehouse):
    item = Item.objects.select_for_update().get(pk=item.pk)
    StockLevel.objects.get_or_create(item=item, warehouse=warehouse)
    level = StockLevel.objects.select_for_update().get(item=item, warehouse=warehouse)
    return item, level


def _record(*, kind, item, warehouse, quantity, unit_cost, user, number, update_cost=False, **extra):
    """
    Enregistre un mouvement (quantité signée) sur l'article déjà verrouillé.
    `update_cost` : entrée valorisée qui recalcule le CMP de l'article.
    """
    if item.tenant_id != warehouse.tenant_id:
        raise ValidationError(_("Magasin d'une autre entreprise."))
    if not warehouse.is_active and quantity > 0:
        raise ValidationError(_("Le magasin %(w)s est désactivé.") % {"w": warehouse.code})
    item, level = _lock(item, warehouse)
    new_quantity = level.quantity + quantity
    if new_quantity < 0:
        raise ValidationError(_("Stock insuffisant : %(ref)s au magasin %(w)s, %(q)s en stock.") % {
            "ref": item.reference, "w": warehouse.code, "q": fmt(level.quantity),
        })
    unit_cost = Decimal(unit_cost).quantize(Q4, rounding=ROUND_HALF_UP)
    if quantity > 0 and update_cost:
        total_before = physical_quantity(item)
        if total_before <= 0 or item.average_cost <= 0:
            item.average_cost = unit_cost
        else:
            item.average_cost = ((total_before * item.average_cost + quantity * unit_cost) / (total_before + quantity)).quantize(
                Q4, rounding=ROUND_HALF_UP)
        item.save(update_fields=["average_cost", "updated_at"])
    level.quantity = new_quantity
    level.save(update_fields=["quantity", "updated_at"])
    return StockMovement.objects.create(
        number=number, kind=kind, item=item, warehouse=warehouse, quantity=quantity, unit_cost=unit_cost,
        value=(quantity * unit_cost).quantize(Q3, rounding=ROUND_HALF_UP), stock_after=new_quantity,
        average_cost_after=item.average_cost, created_by=user, **extra,
    )


def _check_available(item, warehouse, quantity):
    free = physical_quantity(item, warehouse) - reserved_quantity(item, warehouse)
    if quantity > free:
        raise ValidationError(_(
            "Quantité non disponible : %(ref)s au magasin %(w)s, %(free)s disponible(s) "
            "(le reste est réservé pour des OT)."
        ) % {"ref": item.reference, "w": warehouse.code, "free": fmt(max(free, ZERO))})


def _log(user, movement, label):
    log_action(AuditLog.Action.CREATE, user=user, obj=movement, username="" if user else "système",
               changes={label: ["", f"{movement.item.reference} {fmt(movement.quantity)} ({movement.warehouse.code})"]})


# --- Opérations du magasin -----------------------------------------------------------------

def _update_supplier_price(item, supplier, unit_cost, user):
    """Le prix payé à la dernière entrée devient le prix de l'article chez ce fournisseur."""
    if supplier is None:
        return
    link, created = ItemSupplier.objects.get_or_create(
        item=item, supplier=supplier,
        defaults={"price": unit_cost, "created_by": user,
                  "is_preferred": not ItemSupplier.objects.filter(item=item, is_preferred=True).exists()},
    )
    if not created and link.price != unit_cost:
        link.price = unit_cost
        link.save(update_fields=["price", "updated_at"])


@transaction.atomic
def receive(*, item, warehouse, quantity, unit_cost, user, document="", reason="", supplier=None, purchase_order="",
            moved_at=None, number=None):
    """Entrée en stock (réception, apport) : valorisée, recalcule le CMP, met à jour le prix fournisseur."""
    quantity = _positive(quantity)
    unit_cost = _qty(unit_cost, _("Coût unitaire"))
    if unit_cost < 0:
        raise ValidationError(_("Le coût unitaire ne peut pas être négatif."))
    movement = _record(kind=K.RECEIPT, item=item, warehouse=warehouse, quantity=quantity, unit_cost=unit_cost, user=user,
                       number=number or next_document_number("MVT"), update_cost=True, document=document, reason=reason,
                       supplier=supplier, purchase_order=(purchase_order or "").strip()[:40], moved_at=moved_at or timezone.now())
    _update_supplier_price(item, supplier, unit_cost, user)
    _log(user, movement, _("Entrée en stock"))
    return movement


@transaction.atomic
def receive_order(*, supplier, warehouse, purchase_order, lines, user, delivery_note="", moved_at=None):
    """
    Entrée de toutes les lignes d'un bon de commande papier (prix du BC), sous un seul numéro
    de mouvement. `lines` : [(article, quantité, prix unitaire HT)]. Tout ou rien.
    """
    purchase_order = (purchase_order or "").strip()
    if not purchase_order:
        raise ValidationError(_("Indiquez le n° du bon de commande."))
    if not lines:
        raise ValidationError(_("Saisissez au moins une ligne."))
    number, moved_at = next_document_number("MVT"), moved_at or timezone.now()
    return [
        receive(item=item, warehouse=warehouse, quantity=quantity, unit_cost=cost, user=user, supplier=supplier,
                purchase_order=purchase_order, document=delivery_note, reason=_("Réception sur bon de commande"),
                moved_at=moved_at, number=number)
        for item, quantity, cost in lines
    ]


def price_history(item):
    """Prix d'achat constatés aux entrées (fournisseur, BC, prix unitaire HT), du plus récent au plus ancien."""
    return (StockMovement.objects.filter(item=item, kind=K.RECEIPT)
            .select_related("supplier", "warehouse").order_by("-moved_at", "-pk"))


# --- Demandes d'achat ---------------------------------------------------------------------------

UNIT_COUNTED = {"u", "jeu", "paire", "boite"}


def reorder_quantity(item, available):
    """Quantité à demander pour ramener le disponible au maximum (à défaut au minimum)."""
    target = item.max_stock if item.max_stock is not None and item.max_stock > item.min_stock else item.min_stock
    quantity = target - available
    if quantity <= 0:
        return ZERO
    if item.unit in UNIT_COUNTED:
        quantity = quantity.to_integral_value(rounding="ROUND_CEILING")
    return quantity.quantize(Q3)


@transaction.atomic
def save_purchase_request(request_obj, lines, *, user):
    """Enregistre l'en-tête et remplace les lignes. `lines` : dicts (item, reference, designation, quantity, unit, estimated_price)."""
    if not lines:
        raise ValidationError(_("Ajoutez au moins une ligne à la demande d'achat."))
    created = request_obj.pk is None
    if created:
        request_obj.number = next_document_number("DA")
        request_obj.created_by = user
    request_obj.full_clean(exclude=["number"])
    request_obj.save()
    request_obj.lines.all().delete()
    for position, line in enumerate(lines, start=1):
        PurchaseRequestLine.objects.create(request=request_obj, position=position, created_by=user, **line)
    log_action(AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE, user=user, obj=request_obj,
               changes={_("Demande d'achat"): ["", _("%(n)s ligne(s)") % {"n": len(lines)}]})
    return request_obj


def reorder_lines(items):
    """Lignes de DA pour des articles (annotés `available`) : quantité de réapprovisionnement, prix connu."""
    lines = []
    for item in items:
        quantity = reorder_quantity(item, item.available)
        if quantity <= 0:
            continue
        link = item.suppliers.filter(is_preferred=True).first() or item.suppliers.first()
        lines.append({
            "item": item, "reference": (link.supplier_reference if link and link.supplier_reference else item.reference)[:80],
            "designation": item.designation, "quantity": quantity, "unit": item.get_unit_display(),
            "estimated_price": (link.price if link and link.price is not None else item.unit_price) or None,
        })
    return lines


@transaction.atomic
def create_reorder_requests(items, *, user):
    """Une DA par fournisseur principal (et une « fournisseur à définir ») pour les articles donnés."""
    by_supplier = {}
    for item in items:
        link = item.suppliers.filter(is_preferred=True).select_related("supplier").first()
        by_supplier.setdefault(link.supplier if link else None, []).append(item)
    created = []
    for supplier, group in sorted(by_supplier.items(), key=lambda entry: entry[0].name if entry[0] else "~"):
        lines = reorder_lines(group)
        if lines:
            request_obj = PurchaseRequest(supplier=supplier, reason=_("Réapprovisionnement : articles sous le stock minimum"),
                                          is_urgent=any(item.is_critical for item in group))
            created.append(save_purchase_request(request_obj, lines, user=user))
    return created


@transaction.atomic
def issue(*, item, warehouse, quantity, user, reason, document="", equipment=None, moved_at=None):
    """Sortie hors OT (consommation diverse, mise au rebut…) : motif obligatoire, réservé intouchable."""
    quantity = _positive(quantity)
    if not (reason or "").strip():
        raise ValidationError(_("Indiquez le motif de la sortie."))
    item = Item.objects.select_for_update().get(pk=item.pk)
    _check_available(item, warehouse, quantity)
    movement = _record(kind=K.ISSUE, item=item, warehouse=warehouse, quantity=-quantity, unit_cost=item.valuation_cost,
                       user=user, number=next_document_number("MVT"), reason=reason.strip(), document=document,
                       equipment=equipment, moved_at=moved_at or timezone.now())
    _log(user, movement, _("Sortie de stock"))
    return movement


@transaction.atomic
def transfer(*, item, source, destination, quantity, user, reason="", moved_at=None):
    """Transfert entre magasins : deux mouvements de même numéro, au CMP (inchangé)."""
    quantity = _positive(quantity)
    if source.pk == destination.pk:
        raise ValidationError(_("Choisissez deux magasins différents."))
    if not destination.is_active:
        raise ValidationError(_("Le magasin %(w)s est désactivé.") % {"w": destination.code})
    item = Item.objects.select_for_update().get(pk=item.pk)
    _check_available(item, source, quantity)
    number = next_document_number("MVT")
    moved_at = moved_at or timezone.now()
    cost = item.valuation_cost
    out = _record(kind=K.TRANSFER_OUT, item=item, warehouse=source, quantity=-quantity, unit_cost=cost, user=user,
                  number=number, reason=reason, document=destination.code, moved_at=moved_at)
    _record(kind=K.TRANSFER_IN, item=item, warehouse=destination, quantity=quantity, unit_cost=cost, user=user,
            number=number, reason=reason, document=source.code, moved_at=moved_at)
    _log(user, out, _("Transfert"))
    return out


@transaction.atomic
def adjust(*, item, warehouse, new_quantity, user, reason, moved_at=None):
    """Ajustement : le stock du magasin est porté à `new_quantity` (correction d'erreur, casse…)."""
    new_quantity = _qty(new_quantity)
    if new_quantity < 0:
        raise ValidationError(_("Le stock ne peut pas être négatif."))
    if not (reason or "").strip():
        raise ValidationError(_("Indiquez le motif de l'ajustement."))
    item, level = _lock(item, warehouse)
    delta = new_quantity - level.quantity
    if delta == 0:
        raise ValidationError(_("Le stock est déjà de %(q)s.") % {"q": fmt(new_quantity)})
    movement = _record(kind=K.ADJUSTMENT, item=item, warehouse=warehouse, quantity=delta, unit_cost=item.valuation_cost,
                       user=user, number=next_document_number("MVT"), update_cost=delta > 0, reason=reason.strip(),
                       moved_at=moved_at or timezone.now())
    _log(user, movement, _("Ajustement de stock"))
    return movement


# --- Pièces demandées pour les OT -----------------------------------------------------------

def default_warehouse(item):
    """Magasin proposé pour une demande : celui qui a le plus de stock, à défaut le premier actif."""
    level = (StockLevel.objects.filter(item=item, warehouse__is_active=True, quantity__gt=0)
             .select_related("warehouse").order_by("-quantity", "warehouse__code").first())
    if level is not None:
        return level.warehouse
    return Warehouse.objects.filter(is_active=True).order_by("code").first()


@transaction.atomic
def request_part(*, work_order, item, quantity, user, warehouse=None, note="", from_plan=False):
    """Demande (et réserve) une pièce du magasin pour un OT ouvert."""
    if not work_order.is_open:
        raise ValidationError(_("OT clôturé : plus de demande de pièce possible."))
    if not item.is_active:
        raise ValidationError(_("L'article %(ref)s est désactivé.") % {"ref": item.reference})
    quantity = _positive(quantity)
    warehouse = warehouse or default_warehouse(item)
    if warehouse is None:
        raise ValidationError(_("Aucun magasin n'est défini."))
    if not warehouse.is_active:
        raise ValidationError(_("Le magasin %(w)s est désactivé.") % {"w": warehouse.code})
    line = WorkOrderPart.objects.create(
        work_order=work_order, item=item, warehouse=warehouse, quantity=quantity, note=(note or "")[:255],
        from_plan=from_plan, created_by=user,
    )
    log_action(AuditLog.Action.CREATE, user=user, obj=work_order, username="" if user else "système",
               changes={_("Pièce demandée"): ["", f"{item.reference} × {fmt(quantity)} ({warehouse.code})"]})
    return line


def _locked_line(line):
    return WorkOrderPart.objects.select_for_update(of=("self",)).select_related("work_order", "item", "warehouse").get(pk=line.pk)


@transaction.atomic
def issue_request(line, *, quantity, user, moved_at=None):
    """Délivrance par le magasin : sortie de stock au CMP, imputée à l'OT."""
    line = _locked_line(line)
    if not line.is_open:
        raise ValidationError(_("Cette demande est déjà soldée."))
    work_order = line.work_order
    if work_order.status in ("validated", "cancelled"):
        raise ValidationError(_("OT clôturé : plus de délivrance possible."))
    quantity = _positive(quantity)
    if quantity > line.quantity - line.issued:
        raise ValidationError(_("Il reste %(q)s à délivrer sur cette demande.") % {"q": fmt(line.quantity - line.issued)})
    item = Item.objects.select_for_update().get(pk=line.item_id)
    movement = _record(kind=K.ISSUE, item=item, warehouse=line.warehouse, quantity=-quantity, unit_cost=item.valuation_cost,
                       user=user, number=next_document_number("MVT"), document=work_order.number, work_order=work_order,
                       request_line=line, equipment=work_order.equipment, moved_at=moved_at or timezone.now())
    line.issued += quantity
    line.issued_value += -movement.value
    line.status = WorkOrderPart.Status.ISSUED if line.issued >= line.quantity else WorkOrderPart.Status.PARTIAL
    line.save(update_fields=["issued", "issued_value", "status", "updated_at"])
    _log(user, movement, _("Délivrance pour %(ot)s") % {"ot": work_order.number})
    return movement


@transaction.atomic
def return_request(line, *, quantity, user, reason=""):
    """Retour au magasin d'une pièce délivrée non utilisée : entrée au coût de sortie."""
    line = _locked_line(line)
    quantity = _positive(quantity)
    net = line.issued - line.returned
    if quantity > net:
        raise ValidationError(_("Seules %(q)s unité(s) ont été délivrées et non retournées.") % {"q": fmt(net)})
    if line.work_order.status == "validated":
        raise ValidationError(_("OT validé : ses coûts sont figés, faites une entrée en stock ordinaire."))
    unit_cost = (line.issued_value / net).quantize(Q4, rounding=ROUND_HALF_UP) if net else ZERO
    movement = _record(kind=K.RETURN, item=line.item, warehouse=line.warehouse, quantity=quantity, unit_cost=unit_cost,
                       user=user, number=next_document_number("MVT"), update_cost=True, document=line.work_order.number,
                       work_order=line.work_order, request_line=line, equipment=line.work_order.equipment,
                       reason=reason or _("Pièce non utilisée"), moved_at=timezone.now())
    line.returned += quantity
    line.issued_value = max(line.issued_value - movement.value, ZERO)
    line.save(update_fields=["returned", "issued_value", "updated_at"])
    _log(user, movement, _("Retour de %(ot)s") % {"ot": line.work_order.number})
    return movement


@transaction.atomic
def cancel_request(line, *, user):
    """Annule le reste d'une demande : la réservation est libérée."""
    line = _locked_line(line)
    if not line.is_open:
        raise ValidationError(_("Cette demande est déjà soldée."))
    line.status = WorkOrderPart.Status.CANCELLED if line.issued == 0 else WorkOrderPart.Status.CLOSED
    line.save(update_fields=["status", "updated_at"])
    log_action(AuditLog.Action.UPDATE, user=user, obj=line.work_order,
               changes={_("Pièce demandée"): [f"{line.item.reference} × {fmt(line.quantity)}", line.get_status_display()]})
    return line


def release_open_requests(work_order):
    """À la validation ou à l'annulation d'un OT, les quantités non délivrées ne sont plus réservées."""
    for line in WorkOrderPart.objects.filter(work_order=work_order, status__in=WorkOrderPart.OPEN_STATUSES):
        line.status = WorkOrderPart.Status.CANCELLED if line.issued == 0 else WorkOrderPart.Status.CLOSED
        line.save(update_fields=["status", "updated_at"])


def on_work_order_closed(sender, work_order, outcome, **kwargs):
    release_open_requests(work_order)


def reserve_plan_parts(work_order, plan, *, user=None):
    """Pièces du plan préventif reliées au magasin : demandées (réservées) dès la création de l'OT."""
    created = []
    for part in plan.parts.filter(item__isnull=False).select_related("item"):
        if not part.item.is_active or part.quantity <= 0:
            continue
        try:
            created.append(request_part(work_order=work_order, item=part.item, quantity=part.quantity, user=user,
                                        note=_("Prévue par le plan %(c)s") % {"c": plan.code}, from_plan=True))
        except ValidationError:
            continue  # aucun magasin défini : la pièce reste affichée comme prévue
    return created


# --- Inventaires --------------------------------------------------------------------------------

@transaction.atomic
def start_count(*, warehouse, user, family=None, notes=""):
    """Ouvre un inventaire : une ligne par article actif présent dans le magasin, stock théorique figé."""
    if StockCount.objects.filter(warehouse=warehouse, status=StockCount.Status.OPEN).exists():
        raise ValidationError(_("Un inventaire est déjà en cours sur ce magasin."))
    levels = StockLevel.objects.filter(warehouse=warehouse, item__is_active=True).select_related("item")
    if family is not None:
        levels = levels.filter(item__family=family)
    count = StockCount.objects.create(number=next_document_number("INV"), warehouse=warehouse, family=family,
                                      notes=notes, created_by=user)
    StockCountLine.objects.bulk_create([
        StockCountLine(tenant_id=count.tenant_id, count=count, item=level.item, expected=level.quantity, created_by=user)
        for level in levels.order_by("item__reference")
    ])
    log_action(AuditLog.Action.CREATE, user=user, obj=count, changes={_("Magasin"): ["", warehouse.code]})
    return count


@transaction.atomic
def add_count_line(count, *, item, user):
    """Article trouvé en rayon mais absent de la liste."""
    if count.status != StockCount.Status.OPEN:
        raise ValidationError(_("Cet inventaire est clos."))
    if count.lines.filter(item=item).exists():
        raise ValidationError(_("Cet article est déjà dans l'inventaire."))
    return StockCountLine.objects.create(count=count, item=item, expected=physical_quantity(item, count.warehouse), created_by=user)


@transaction.atomic
def save_counts(count, values):
    """`values` : {id de ligne: texte saisi}. Vide = non compté."""
    if count.status != StockCount.Status.OPEN:
        raise ValidationError(_("Cet inventaire est clos."))
    errors = []
    lines = {line.pk: line for line in count.lines.select_related("item")}
    for pk, raw in values.items():
        line = lines.get(pk)
        if line is None:
            continue
        text = (raw or "").strip().replace(",", ".")
        if text == "":
            counted = None
        else:
            try:
                counted = Decimal(text).quantize(Q3, rounding=ROUND_HALF_UP)
            except Exception:
                errors.append(_("%(ref)s : « %(v)s » n'est pas un nombre.") % {"ref": line.item.reference, "v": raw})
                continue
            if counted < 0:
                errors.append(_("%(ref)s : quantité négative.") % {"ref": line.item.reference})
                continue
        if counted != line.counted:
            line.counted = counted
            line.save(update_fields=["counted", "updated_at"])
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def validate_count(count, *, user):
    """
    Valide l'inventaire : pour chaque article compté, le stock du magasin est porté à la quantité
    comptée (mouvement « Inventaire » de l'écart). Les articles non comptés ne changent pas.
    """
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != StockCount.Status.OPEN:
        raise ValidationError(_("Cet inventaire est déjà clos."))
    lines = list(count.lines.filter(counted__isnull=False).select_related("item"))
    if not lines:
        raise ValidationError(_("Aucune quantité comptée."))
    moved_at = timezone.now()
    for line in lines:
        item, level = _lock(line.item, count.warehouse)
        delta = line.counted - level.quantity
        line.adjustment = delta
        line.save(update_fields=["adjustment", "updated_at"])
        if delta != 0:
            _record(kind=K.INVENTORY, item=item, warehouse=count.warehouse, quantity=delta, unit_cost=item.valuation_cost,
                    user=user, number=count.number, update_cost=delta > 0, document=count.number,
                    reason=_("Écart d'inventaire"), count=count, moved_at=moved_at)
    count.status = StockCount.Status.VALIDATED
    count.validated_at, count.validated_by = moved_at, user
    count.save(update_fields=["status", "validated_at", "validated_by", "updated_at"])
    log_action(AuditLog.Action.UPDATE, user=user, obj=count, changes={_("Statut"): [_("En cours"), _("Validé")]})
    return count


@transaction.atomic
def cancel_count(count, *, user):
    if count.status != StockCount.Status.OPEN:
        raise ValidationError(_("Cet inventaire est déjà clos."))
    count.status = StockCount.Status.CANCELLED
    count.save(update_fields=["status", "updated_at"])
    log_action(AuditLog.Action.UPDATE, user=user, obj=count, changes={_("Statut"): [_("En cours"), _("Annulé")]})
    return count
