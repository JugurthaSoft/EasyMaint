from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.assets.forms import DateInput
from apps.assets.models import Equipment, Manufacturer
from apps.workorders.forms import EquipmentChoiceField
from apps.workorders.models import WorkOrder

from .models import Item, ItemSupplier, PartFamily, PurchaseRequest, Supplier, Warehouse

MIN_QTY = Decimal("0.001")


class ItemReferenceField(forms.CharField):
    """Article saisi par sa référence (liste de suggestions dans la page), résolu dans l'entreprise courante."""

    def __init__(self, *args, active_only=True, **kwargs):
        kwargs.setdefault("label", _("Article"))
        kwargs.setdefault("max_length", 40)
        super().__init__(*args, **kwargs)
        self.active_only = active_only
        self.widget.attrs.update({"list": "items-datalist", "autocomplete": "off", "placeholder": _("Référence")})

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        reference = value.split(" · ")[0].strip()
        items = Item.objects.filter(reference__iexact=reference)
        if self.active_only:
            items = items.filter(is_active=True)
        item = items.first()
        if item is None:
            raise forms.ValidationError(_("Article « %(r)s » introuvable.") % {"r": reference})
        return item


def _warehouses():
    return Warehouse.objects.filter(is_active=True).order_by("code")


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "reference", "designation", "family", "brand", "manufacturer", "manufacturer_reference", "unit",
            "unit_price", "min_stock", "max_stock", "lead_time_days", "is_critical", "is_active", "photo", "datasheet", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "photo": forms.FileInput(attrs={"accept": "image/*"}),
            "datasheet": forms.FileInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["family"].queryset = PartFamily.objects.order_by("name")
        self.fields["manufacturer"].queryset = Manufacturer.objects.order_by("name")

    def clean_reference(self):
        reference = self.cleaned_data["reference"].strip().upper()
        duplicates = Item.objects.filter(reference__iexact=reference)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("Cette référence existe déjà."))
        return reference


class _CodeForm(forms.ModelForm):
    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        duplicates = self._meta.model.objects.filter(code__iexact=code)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("Ce code est déjà utilisé."))
        return code


class FamilyForm(_CodeForm):
    class Meta:
        model = PartFamily
        fields = ["code", "name"]


class WarehouseForm(_CodeForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name", "location", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.assets.models import Location

        self.fields["location"].queryset = Location.objects.order_by("name")


class SupplierForm(_CodeForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "contact_name", "phone", "email", "tax_id", "address", "notes", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}


class ItemSupplierForm(forms.ModelForm):
    class Meta:
        model = ItemSupplier
        fields = ["supplier", "supplier_reference", "price", "lead_time_days", "is_preferred"]

    def __init__(self, *args, item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.item = item
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)

    def clean_supplier(self):
        supplier = self.cleaned_data["supplier"]
        if self.item is not None and ItemSupplier.objects.filter(item=self.item, supplier=supplier).exists():
            raise forms.ValidationError(_("Ce fournisseur est déjà associé à l'article."))
        return supplier


class BinForm(forms.Form):
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())
    bin_location = forms.CharField(label=_("Emplacement"), max_length=60, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = _warehouses()


class _MovementForm(forms.Form):
    item = ItemReferenceField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("warehouse", "source", "destination"):
            if name in self.fields:
                self.fields[name].queryset = _warehouses()


class ReceiptForm(_MovementForm):
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())
    quantity = forms.DecimalField(label=_("Quantité"), max_digits=12, decimal_places=3, min_value=MIN_QTY)
    unit_cost = forms.DecimalField(label=_("Coût unitaire HT"), max_digits=14, decimal_places=3, min_value=Decimal("0"))
    supplier = forms.ModelChoiceField(label=_("Fournisseur"), queryset=Supplier.objects.none(), required=False)
    purchase_order = forms.CharField(label=_("N° de bon de commande"), max_length=40, required=False)
    document = forms.CharField(label=_("N° de bon de livraison"), max_length=100, required=False)
    reason = forms.CharField(label=_("Motif"), max_length=255, required=False, initial=_("Réception fournisseur"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)


class IssueForm(_MovementForm):
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())
    quantity = forms.DecimalField(label=_("Quantité"), max_digits=12, decimal_places=3, min_value=MIN_QTY)
    equipment = EquipmentChoiceField(label=_("Équipement (facultatif)"), queryset=Equipment.objects.none(), required=False)
    reason = forms.CharField(label=_("Motif"), max_length=255, help_text=_("Pour une pièce destinée à un OT, demandez-la depuis l'OT."))
    document = forms.CharField(label=_("Document associé"), max_length=100, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment"].queryset = Equipment.objects.exclude(status=Equipment.Status.RETIRED).order_by("code")


class TransferForm(_MovementForm):
    source = forms.ModelChoiceField(label=_("Magasin de départ"), queryset=Warehouse.objects.none())
    destination = forms.ModelChoiceField(label=_("Magasin d'arrivée"), queryset=Warehouse.objects.none())
    quantity = forms.DecimalField(label=_("Quantité"), max_digits=12, decimal_places=3, min_value=MIN_QTY)
    reason = forms.CharField(label=_("Motif"), max_length=255, required=False)


class AdjustForm(_MovementForm):
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())
    new_quantity = forms.DecimalField(label=_("Nouveau stock du magasin"), max_digits=12, decimal_places=3, min_value=Decimal("0"))
    reason = forms.CharField(label=_("Motif"), max_length=255, help_text=_("Erreur de saisie, casse, péremption…"))


MOVEMENT_FORMS = {
    "entree": (ReceiptForm, _("Entrée en stock")),
    "sortie": (IssueForm, _("Sortie hors OT")),
    "transfert": (TransferForm, _("Transfert entre magasins")),
    "ajustement": (AdjustForm, _("Ajustement de stock")),
}


class PartRequestForm(forms.Form):
    item = ItemReferenceField()
    quantity = forms.DecimalField(label=_("Quantité"), max_digits=12, decimal_places=3, min_value=MIN_QTY, initial=1)
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none(), required=False,
                                       empty_label=_("— Le mieux approvisionné —"))
    note = forms.CharField(label=_("Commentaire"), max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = _warehouses()


class QuantityForm(forms.Form):
    quantity = forms.DecimalField(label=_("Quantité"), max_digits=12, decimal_places=3, min_value=MIN_QTY)
    reason = forms.CharField(label=_("Motif"), max_length=255, required=False)


class EquipmentPartForm(forms.Form):
    item = ItemReferenceField()
    quantity = forms.DecimalField(label=_("Quantité montée"), max_digits=12, decimal_places=3, min_value=MIN_QTY, initial=1)
    position = forms.CharField(label=_("Repère / emplacement"), max_length=150, required=False)


class CountStartForm(forms.Form):
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())
    family = forms.ModelChoiceField(label=_("Famille (facultatif)"), queryset=PartFamily.objects.none(), required=False,
                                    empty_label=_("— Tout le magasin —"))
    notes = forms.CharField(label=_("Notes"), required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = _warehouses()
        self.fields["family"].queryset = PartFamily.objects.order_by("name")



class PurchaseRequestForm(forms.ModelForm):
    class Meta:
        model = PurchaseRequest
        fields = ["requested_on", "supplier", "reason", "work_order", "equipment", "needed_by", "is_urgent", "notes"]
        widgets = {"requested_on": DateInput(), "needed_by": DateInput(), "notes": forms.Textarea(attrs={"rows": 2})}

    equipment = EquipmentChoiceField(label=_("Équipement concerné"), queryset=Equipment.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["equipment"].queryset = Equipment.objects.exclude(status=Equipment.Status.RETIRED).order_by("code")
        open_orders = WorkOrder.objects.filter(status__in=WorkOrder.OPEN_STATUSES)
        if self.instance.work_order_id:
            open_orders = open_orders | WorkOrder.objects.filter(pk=self.instance.work_order_id)
        self.fields["work_order"].queryset = open_orders.select_related("equipment").order_by("-pk")
        self.fields["work_order"].label_from_instance = lambda wo: f"{wo.number} · {wo.equipment.code} · {wo.title[:50]}"


class OrderReceiptForm(forms.Form):
    """En-tête d'une entrée sur bon de commande papier."""

    supplier = forms.ModelChoiceField(label=_("Fournisseur"), queryset=Supplier.objects.none())
    purchase_order = forms.CharField(label=_("N° de bon de commande"), max_length=40)
    delivery_note = forms.CharField(label=_("N° de bon de livraison"), max_length=100, required=False)
    warehouse = forms.ModelChoiceField(label=_("Magasin"), queryset=Warehouse.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["warehouse"].queryset = _warehouses()


def parse_rows(data, prefix, count, fields):
    """Lignes saisies dans une grille (`<prefix>-<n>-<champ>`) ; les lignes entièrement vides sont ignorées."""
    rows = []
    for index in range(count):
        values = {name: (data.get(f"{prefix}-{index}-{name}") or "").strip() for name in fields}
        if any(values.values()):
            rows.append((index + 1, values))
    return rows


def to_decimal(text):
    text = (text or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        raise forms.ValidationError(_("« %(v)s » n'est pas un nombre.") % {"v": text}) from None


def find_item(reference, active_only=True):
    reference = (reference or "").split(" · ")[0].strip()
    if not reference:
        return None
    items = Item.objects.filter(reference__iexact=reference)
    if active_only:
        items = items.filter(is_active=True)
    item = items.first()
    if item is None:
        raise forms.ValidationError(_("Article « %(r)s » introuvable.") % {"r": reference})
    return item
