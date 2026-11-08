"""
Pièces de rechange et stocks.

- Un article est unique par référence dans l'entreprise ; son stock est tenu par magasin.
- Valorisation au coût moyen pondéré (CMP) : recalculé à chaque entrée (réception, retour),
  inchangé par les sorties et transferts.
- Chaque mouvement est définitif : on ne le modifie ni ne le supprime, on le corrige par un
  mouvement inverse (ajustement, retour). L'historique est donc complet et non destructif.
- Stock négatif interdit.
- Les pièces demandées pour un OT sont réservées jusqu'à leur délivrance par le magasin.
"""
import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.assets.models import Equipment, Location, Manufacturer
from apps.core.models import TenantScopedModel, validate_attachment
from apps.workorders.models import WorkOrder

ZERO = Decimal("0")


class PartFamily(TenantScopedModel):
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("nom"), max_length=120)

    class Meta:
        verbose_name = _("famille d'articles")
        verbose_name_plural = _("familles d'articles")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_part_family_code_per_tenant")]

    def __str__(self):
        return self.name


class Warehouse(TenantScopedModel):
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("nom"), max_length=120)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                 verbose_name=_("localisation"))
    is_active = models.BooleanField(_("actif"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("magasin")
        verbose_name_plural = _("magasins")
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_warehouse_code_per_tenant")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def clean(self):
        self.check_same_tenant(location=self.location)


class Supplier(TenantScopedModel):
    code = models.CharField(_("code"), max_length=30)
    name = models.CharField(_("raison sociale"), max_length=150)
    contact_name = models.CharField(_("contact"), max_length=150, blank=True)
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    address = models.TextField(_("adresse"), blank=True)
    tax_id = models.CharField(_("matricule fiscal"), max_length=40, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("actif"), default=True)

    class Meta:
        verbose_name = _("fournisseur")
        verbose_name_plural = _("fournisseurs")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uniq_supplier_code_per_tenant")]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("inventory:supplier_detail", args=[self.pk])


def item_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"tenant_{instance.tenant_id}/articles/{uuid.uuid4().hex}{ext}"


class Item(TenantScopedModel):
    class Unit(models.TextChoices):
        PIECE = "u", _("pièce")
        SET = "jeu", _("jeu")
        PAIR = "paire", _("paire")
        BOX = "boite", _("boîte")
        METER = "m", _("mètre")
        KILOGRAM = "kg", _("kilogramme")
        LITER = "l", _("litre")

    reference = models.CharField(_("référence"), max_length=40)
    designation = models.CharField(_("désignation"), max_length=200)
    family = models.ForeignKey(PartFamily, on_delete=models.PROTECT, null=True, blank=True, related_name="items",
                               verbose_name=_("famille"))
    brand = models.CharField(_("marque"), max_length=100, blank=True)
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name=_("fabricant"))
    manufacturer_reference = models.CharField(_("référence constructeur"), max_length=80, blank=True)
    unit = models.CharField(_("unité"), max_length=10, choices=Unit.choices, default=Unit.PIECE)
    photo = models.ImageField(_("photo"), upload_to=item_upload_to, blank=True)
    datasheet = models.FileField(_("fiche technique"), upload_to=item_upload_to, blank=True, validators=[validate_attachment])
    unit_price = models.DecimalField(_("prix de référence"), max_digits=14, decimal_places=3, default=0,
                                     help_text=_("Prix d'achat habituel, utilisé tant qu'aucune entrée n'a fixé le coût moyen."))
    average_cost = models.DecimalField(_("coût moyen pondéré"), max_digits=14, decimal_places=4, default=0, editable=False)
    min_stock = models.DecimalField(_("stock minimum"), max_digits=12, decimal_places=3, default=0)
    max_stock = models.DecimalField(_("stock maximum"), max_digits=12, decimal_places=3, null=True, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(_("délai d'approvisionnement (jours)"), null=True, blank=True)
    is_critical = models.BooleanField(_("pièce critique"), default=False,
                                      help_text=_("Pièce dont l'absence arrête un équipement important."))
    is_active = models.BooleanField(_("actif"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("article")
        verbose_name_plural = _("articles")
        ordering = ["reference"]
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_item_reference_per_tenant")]

    def __str__(self):
        return f"{self.reference} · {self.designation}"

    def get_absolute_url(self):
        return reverse("inventory:item_detail", args=[self.pk])

    def clean(self):
        self.check_same_tenant(family=self.family, manufacturer=self.manufacturer)
        if self.max_stock is not None and self.min_stock is not None and self.max_stock < self.min_stock:
            raise ValidationError({"max_stock": _("Le stock maximum doit être supérieur ou égal au minimum.")})

    @property
    def valuation_cost(self):
        """Coût utilisé pour valoriser : le CMP, à défaut le prix de référence."""
        return self.average_cost or self.unit_price or ZERO


class ItemSupplier(TenantScopedModel):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="suppliers", verbose_name=_("article"))
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="items", verbose_name=_("fournisseur"))
    supplier_reference = models.CharField(_("référence fournisseur"), max_length=80, blank=True)
    price = models.DecimalField(_("prix"), max_digits=14, decimal_places=3, null=True, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(_("délai (jours)"), null=True, blank=True)
    is_preferred = models.BooleanField(_("fournisseur principal"), default=False)

    class Meta:
        verbose_name = _("fournisseur de l'article")
        verbose_name_plural = _("fournisseurs de l'article")
        ordering = ["-is_preferred", "supplier__name"]
        constraints = [models.UniqueConstraint(fields=["tenant", "item", "supplier"], name="uniq_item_supplier")]

    def __str__(self):
        return f"{self.item.reference} · {self.supplier}"

    def clean(self):
        self.check_same_tenant(item=self.item if self.item_id else None, supplier=self.supplier if self.supplier_id else None)


class StockLevel(TenantScopedModel):
    """Quantité physique d'un article dans un magasin (tenue par les mouvements, jamais saisie)."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="stock_levels", verbose_name=_("article"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels", verbose_name=_("magasin"))
    quantity = models.DecimalField(_("quantité"), max_digits=12, decimal_places=3, default=0)
    bin_location = models.CharField(_("emplacement"), max_length=60, blank=True, help_text=_("Allée, rayon, casier…"))

    class Meta:
        verbose_name = _("stock par magasin")
        verbose_name_plural = _("stocks par magasin")
        ordering = ["warehouse__code"]
        constraints = [models.UniqueConstraint(fields=["tenant", "item", "warehouse"], name="uniq_stock_level")]

    def __str__(self):
        return f"{self.item.reference} @ {self.warehouse.code} : {self.quantity}"


class WorkOrderPart(TenantScopedModel):
    """Pièce du magasin demandée pour un OT : réservée, puis délivrée par le magasinier."""

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Demandée")
        PARTIAL = "partial", _("Partiellement délivrée")
        ISSUED = "issued", _("Délivrée")
        CLOSED = "closed", _("Soldée")
        CANCELLED = "cancelled", _("Annulée")

    OPEN_STATUSES = ("requested", "partial")

    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="stock_parts", verbose_name=_("OT"))
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="requests", verbose_name=_("article"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="requests", verbose_name=_("magasin"))
    quantity = models.DecimalField(_("quantité demandée"), max_digits=12, decimal_places=3)
    issued = models.DecimalField(_("quantité délivrée"), max_digits=12, decimal_places=3, default=0)
    returned = models.DecimalField(_("quantité retournée"), max_digits=12, decimal_places=3, default=0)
    issued_value = models.DecimalField(_("valeur consommée"), max_digits=16, decimal_places=3, default=0)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.REQUESTED)
    note = models.CharField(_("commentaire"), max_length=255, blank=True)
    from_plan = models.BooleanField(_("prévue par le plan préventif"), default=False)

    class Meta:
        verbose_name = _("pièce demandée")
        verbose_name_plural = _("pièces demandées")
        ordering = ["pk"]
        indexes = [models.Index(fields=["tenant", "status"], name="wo_part_status_idx")]

    def __str__(self):
        return f"{self.work_order.number} · {self.item.reference} × {self.quantity}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def remaining(self):
        return max(self.quantity - self.issued, ZERO) if self.is_open else ZERO

    @property
    def consumed(self):
        return self.issued - self.returned

    @property
    def status_badge(self):
        return {"requested": "b-blue", "partial": "b-orange", "issued": "b-green", "closed": "b-gray", "cancelled": "b-gray"}[self.status]


class StockCount(TenantScopedModel):
    """Inventaire physique d'un magasin (éventuellement d'une famille)."""

    class Status(models.TextChoices):
        OPEN = "open", _("En cours")
        VALIDATED = "validated", _("Validé")
        CANCELLED = "cancelled", _("Annulé")

    number = models.CharField(_("numéro"), max_length=20, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="counts", verbose_name=_("magasin"))
    family = models.ForeignKey(PartFamily, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name=_("famille"), help_text=_("Laisser vide pour inventorier tout le magasin."))
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.OPEN)
    started_at = models.DateTimeField(_("ouvert le"), default=timezone.now)
    validated_at = models.DateTimeField(_("validé le"), null=True, blank=True)
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name=_("validé par"))
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("inventaire")
        verbose_name_plural = _("inventaires")
        ordering = ["-started_at"]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("inventory:count_detail", args=[self.pk])


class StockCountLine(TenantScopedModel):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+", verbose_name=_("article"))
    expected = models.DecimalField(_("stock théorique"), max_digits=12, decimal_places=3, default=0)
    counted = models.DecimalField(_("quantité comptée"), max_digits=12, decimal_places=3, null=True, blank=True)
    adjustment = models.DecimalField(_("écart enregistré"), max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        verbose_name = _("ligne d'inventaire")
        verbose_name_plural = _("lignes d'inventaire")
        ordering = ["item__reference"]
        constraints = [models.UniqueConstraint(fields=["tenant", "count", "item"], name="uniq_count_line")]

    @property
    def difference(self):
        return None if self.counted is None else self.counted - self.expected


class StockMovement(TenantScopedModel):
    """Mouvement de stock définitif. Quantité signée : positive en entrée, négative en sortie."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", _("Entrée")
        ISSUE = "issue", _("Sortie")
        RETURN = "return", _("Retour")
        TRANSFER_OUT = "transfer_out", _("Transfert (départ)")
        TRANSFER_IN = "transfer_in", _("Transfert (arrivée)")
        ADJUSTMENT = "adjustment", _("Ajustement")
        INVENTORY = "inventory", _("Inventaire")

    number = models.CharField(_("numéro"), max_length=20)
    kind = models.CharField(_("type"), max_length=15, choices=Kind.choices)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements", verbose_name=_("article"))
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements", verbose_name=_("magasin"))
    quantity = models.DecimalField(_("quantité"), max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(_("coût unitaire"), max_digits=14, decimal_places=4, default=0)
    value = models.DecimalField(_("valeur"), max_digits=16, decimal_places=3, default=0)
    stock_after = models.DecimalField(_("stock après (magasin)"), max_digits=12, decimal_places=3)
    average_cost_after = models.DecimalField(_("CMP après"), max_digits=14, decimal_places=4)
    moved_at = models.DateTimeField(_("date"), default=timezone.now)
    reason = models.CharField(_("motif"), max_length=255, blank=True)
    document = models.CharField(_("document associé"), max_length=100, blank=True,
                                help_text=_("N° de bon de livraison, de facture, de bon de sortie…"))
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements",
                                   verbose_name=_("OT"))
    request_line = models.ForeignKey(WorkOrderPart, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements")
    count = models.ForeignKey(StockCount, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements")
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name=_("équipement"))
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                 verbose_name=_("fournisseur"))
    purchase_order = models.CharField(_("n° de bon de commande"), max_length=40, blank=True,
                                      help_text=_("Bon de commande émis par le service achats."))

    class Meta:
        verbose_name = _("mouvement de stock")
        verbose_name_plural = _("mouvements de stock")
        ordering = ["-moved_at", "-pk"]
        indexes = [models.Index(fields=["item", "moved_at"], name="movement_item_date_idx")]

    def __str__(self):
        return f"{self.number} · {self.get_kind_display()} · {self.item.reference} {self.quantity:+}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(_("Un mouvement de stock ne se modifie pas : enregistrez un mouvement correctif."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Un mouvement de stock ne se supprime pas : enregistrez un mouvement correctif."))

    @property
    def is_entry(self):
        return self.quantity > 0


class EquipmentPart(TenantScopedModel):
    """Nomenclature : pièce de rechange montée sur un équipement."""

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="spare_parts", verbose_name=_("équipement"))
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="equipment_links", verbose_name=_("article"))
    quantity = models.DecimalField(_("quantité montée"), max_digits=12, decimal_places=3, default=1)
    position = models.CharField(_("repère / emplacement"), max_length=150, blank=True)

    class Meta:
        verbose_name = _("pièce de l'équipement")
        verbose_name_plural = _("nomenclature des équipements")
        ordering = ["item__reference"]
        constraints = [models.UniqueConstraint(fields=["tenant", "equipment", "item"], name="uniq_equipment_part")]

    def __str__(self):
        return f"{self.equipment.code} · {self.item.reference}"

    def clean(self):
        self.check_same_tenant(equipment=self.equipment if self.equipment_id else None, item=self.item if self.item_id else None)


class PurchaseRequest(TenantScopedModel):
    """
    Demande d'achat : document imprimé, signé et transmis au service achats, qui gère ensuite
    commande, réception et facture dans son propre logiciel. Pas de circuit ni de suivi ici.
    """

    number = models.CharField(_("numéro"), max_length=20, editable=False)
    requested_on = models.DateField(_("date"), default=timezone.localdate)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_requests",
                                 verbose_name=_("fournisseur suggéré"))
    reason = models.CharField(_("motif"), max_length=255, blank=True,
                              help_text=_("Réapprovisionnement, réparation, amélioration…"))
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name=_("OT concerné"))
    equipment = models.ForeignKey(Equipment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name=_("équipement concerné"))
    needed_by = models.DateField(_("date souhaitée"), null=True, blank=True)
    is_urgent = models.BooleanField(_("urgent"), default=False)
    notes = models.TextField(_("observations"), blank=True)

    class Meta:
        verbose_name = _("demande d'achat")
        verbose_name_plural = _("demandes d'achat")
        ordering = ["-requested_on", "-pk"]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("inventory:purchase_detail", args=[self.pk])

    def clean(self):
        self.check_same_tenant(supplier=self.supplier, work_order=self.work_order, equipment=self.equipment)

    @property
    def estimated_total(self):
        return sum((line.estimated_total for line in self.lines.all()), ZERO)


class PurchaseRequestLine(TenantScopedModel):
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                             verbose_name=_("article du magasin"))
    reference = models.CharField(_("référence"), max_length=80, blank=True)
    designation = models.CharField(_("désignation"), max_length=200)
    quantity = models.DecimalField(_("quantité"), max_digits=12, decimal_places=3)
    unit = models.CharField(_("unité"), max_length=20, blank=True)
    estimated_price = models.DecimalField(_("prix unitaire estimé HT"), max_digits=14, decimal_places=3, null=True, blank=True)
    position = models.PositiveSmallIntegerField(_("ordre"), default=0)

    class Meta:
        verbose_name = _("ligne de demande d'achat")
        verbose_name_plural = _("lignes de demande d'achat")
        ordering = ["position", "pk"]

    def __str__(self):
        return f"{self.reference or ''} {self.designation} × {self.quantity}".strip()

    @property
    def estimated_total(self):
        return (self.quantity * self.estimated_price) if self.estimated_price is not None else ZERO
