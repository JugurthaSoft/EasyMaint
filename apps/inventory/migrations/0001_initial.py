import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.core.models
import apps.inventory.models


def _base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
        ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
        ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
    ]


CASCADE = django.db.models.deletion.CASCADE
PROTECT = django.db.models.deletion.PROTECT
SET_NULL = django.db.models.deletion.SET_NULL

UNITS = [("u", "pièce"), ("jeu", "jeu"), ("paire", "paire"), ("boite", "boîte"), ("m", "mètre"), ("kg", "kilogramme"), ("l", "litre")]
PART_STATUSES = [("requested", "Demandée"), ("partial", "Partiellement délivrée"), ("issued", "Délivrée"), ("closed", "Soldée"), ("cancelled", "Annulée")]
COUNT_STATUSES = [("open", "En cours"), ("validated", "Validé"), ("cancelled", "Annulé")]
KINDS = [
    ("receipt", "Entrée"), ("issue", "Sortie"), ("return", "Retour"), ("transfer_out", "Transfert (départ)"),
    ("transfer_in", "Transfert (arrivée)"), ("adjustment", "Ajustement"), ("inventory", "Inventaire"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        ("assets", "0002_location_kind_unite"),
        ("workorders", "0002_preventive_link"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PartFamily",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=20, verbose_name="code")),
                ("name", models.CharField(max_length=120, verbose_name="nom")),
            ],
            options={"verbose_name": "famille d'articles", "verbose_name_plural": "familles d'articles", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="partfamily",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_part_family_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="Warehouse",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=20, verbose_name="code")),
                ("name", models.CharField(max_length=120, verbose_name="nom")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("location", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="assets.location", verbose_name="localisation")),
            ],
            options={"verbose_name": "magasin", "verbose_name_plural": "magasins", "ordering": ["code"]},
        ),
        migrations.AddConstraint(
            model_name="warehouse",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_warehouse_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="Supplier",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=150, verbose_name="raison sociale")),
                ("contact_name", models.CharField(blank=True, max_length=150, verbose_name="contact")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="téléphone")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("address", models.TextField(blank=True, verbose_name="adresse")),
                ("tax_id", models.CharField(blank=True, max_length=40, verbose_name="matricule fiscal")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
            ],
            options={"verbose_name": "fournisseur", "verbose_name_plural": "fournisseurs", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="supplier",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_supplier_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="Item",
            fields=_base_fields() + [
                ("reference", models.CharField(max_length=40, verbose_name="référence")),
                ("designation", models.CharField(max_length=200, verbose_name="désignation")),
                ("brand", models.CharField(blank=True, max_length=100, verbose_name="marque")),
                ("manufacturer_reference", models.CharField(blank=True, max_length=80, verbose_name="référence constructeur")),
                ("unit", models.CharField(choices=UNITS, default="u", max_length=10, verbose_name="unité")),
                ("photo", models.ImageField(blank=True, upload_to=apps.inventory.models.item_upload_to, verbose_name="photo")),
                ("datasheet", models.FileField(blank=True, upload_to=apps.inventory.models.item_upload_to, validators=[apps.core.models.validate_attachment], verbose_name="fiche technique")),
                ("unit_price", models.DecimalField(decimal_places=3, default=0, help_text="Prix d'achat habituel, utilisé tant qu'aucune entrée n'a fixé le coût moyen.", max_digits=14, verbose_name="prix de référence")),
                ("average_cost", models.DecimalField(decimal_places=4, default=0, editable=False, max_digits=14, verbose_name="coût moyen pondéré")),
                ("min_stock", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="stock minimum")),
                ("max_stock", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="stock maximum")),
                ("lead_time_days", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="délai d'approvisionnement (jours)")),
                ("is_critical", models.BooleanField(default=False, help_text="Pièce dont l'absence arrête un équipement important.", verbose_name="pièce critique")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("family", models.ForeignKey(blank=True, null=True, on_delete=PROTECT, related_name="items", to="inventory.partfamily", verbose_name="famille")),
                ("manufacturer", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="assets.manufacturer", verbose_name="fabricant")),
            ],
            options={"verbose_name": "article", "verbose_name_plural": "articles", "ordering": ["reference"]},
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.UniqueConstraint(fields=("tenant", "reference"), name="uniq_item_reference_per_tenant"),
        ),
        migrations.CreateModel(
            name="ItemSupplier",
            fields=_base_fields() + [
                ("supplier_reference", models.CharField(blank=True, max_length=80, verbose_name="référence fournisseur")),
                ("price", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True, verbose_name="prix")),
                ("lead_time_days", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="délai (jours)")),
                ("is_preferred", models.BooleanField(default=False, verbose_name="fournisseur principal")),
                ("item", models.ForeignKey(on_delete=CASCADE, related_name="suppliers", to="inventory.item", verbose_name="article")),
                ("supplier", models.ForeignKey(on_delete=CASCADE, related_name="items", to="inventory.supplier", verbose_name="fournisseur")),
            ],
            options={"verbose_name": "fournisseur de l'article", "verbose_name_plural": "fournisseurs de l'article", "ordering": ["-is_preferred", "supplier__name"]},
        ),
        migrations.AddConstraint(
            model_name="itemsupplier",
            constraint=models.UniqueConstraint(fields=("tenant", "item", "supplier"), name="uniq_item_supplier"),
        ),
        migrations.CreateModel(
            name="StockLevel",
            fields=_base_fields() + [
                ("quantity", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="quantité")),
                ("bin_location", models.CharField(blank=True, help_text="Allée, rayon, casier…", max_length=60, verbose_name="emplacement")),
                ("item", models.ForeignKey(on_delete=CASCADE, related_name="stock_levels", to="inventory.item", verbose_name="article")),
                ("warehouse", models.ForeignKey(on_delete=PROTECT, related_name="stock_levels", to="inventory.warehouse", verbose_name="magasin")),
            ],
            options={"verbose_name": "stock par magasin", "verbose_name_plural": "stocks par magasin", "ordering": ["warehouse__code"]},
        ),
        migrations.AddConstraint(
            model_name="stocklevel",
            constraint=models.UniqueConstraint(fields=("tenant", "item", "warehouse"), name="uniq_stock_level"),
        ),
        migrations.CreateModel(
            name="WorkOrderPart",
            fields=_base_fields() + [
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12, verbose_name="quantité demandée")),
                ("issued", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="quantité délivrée")),
                ("returned", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="quantité retournée")),
                ("issued_value", models.DecimalField(decimal_places=3, default=0, max_digits=16, verbose_name="valeur consommée")),
                ("status", models.CharField(choices=PART_STATUSES, default="requested", max_length=10, verbose_name="statut")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="commentaire")),
                ("from_plan", models.BooleanField(default=False, verbose_name="prévue par le plan préventif")),
                ("item", models.ForeignKey(on_delete=PROTECT, related_name="requests", to="inventory.item", verbose_name="article")),
                ("warehouse", models.ForeignKey(on_delete=PROTECT, related_name="requests", to="inventory.warehouse", verbose_name="magasin")),
                ("work_order", models.ForeignKey(on_delete=CASCADE, related_name="stock_parts", to="workorders.workorder", verbose_name="OT")),
            ],
            options={"verbose_name": "pièce demandée", "verbose_name_plural": "pièces demandées", "ordering": ["pk"]},
        ),
        migrations.AddIndex(
            model_name="workorderpart",
            index=models.Index(fields=["tenant", "status"], name="wo_part_status_idx"),
        ),
        migrations.CreateModel(
            name="StockCount",
            fields=_base_fields() + [
                ("number", models.CharField(editable=False, max_length=20, verbose_name="numéro")),
                ("status", models.CharField(choices=COUNT_STATUSES, default="open", max_length=10, verbose_name="statut")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="ouvert le")),
                ("validated_at", models.DateTimeField(blank=True, null=True, verbose_name="validé le")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("family", models.ForeignKey(blank=True, help_text="Laisser vide pour inventorier tout le magasin.", null=True, on_delete=SET_NULL, related_name="+", to="inventory.partfamily", verbose_name="famille")),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="validé par")),
                ("warehouse", models.ForeignKey(on_delete=PROTECT, related_name="counts", to="inventory.warehouse", verbose_name="magasin")),
            ],
            options={"verbose_name": "inventaire", "verbose_name_plural": "inventaires", "ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="StockCountLine",
            fields=_base_fields() + [
                ("expected", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="stock théorique")),
                ("counted", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="quantité comptée")),
                ("adjustment", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="écart enregistré")),
                ("count", models.ForeignKey(on_delete=CASCADE, related_name="lines", to="inventory.stockcount")),
                ("item", models.ForeignKey(on_delete=PROTECT, related_name="+", to="inventory.item", verbose_name="article")),
            ],
            options={"verbose_name": "ligne d'inventaire", "verbose_name_plural": "lignes d'inventaire", "ordering": ["item__reference"]},
        ),
        migrations.AddConstraint(
            model_name="stockcountline",
            constraint=models.UniqueConstraint(fields=("tenant", "count", "item"), name="uniq_count_line"),
        ),
        migrations.CreateModel(
            name="StockMovement",
            fields=_base_fields() + [
                ("number", models.CharField(max_length=20, verbose_name="numéro")),
                ("kind", models.CharField(choices=KINDS, max_length=15, verbose_name="type")),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12, verbose_name="quantité")),
                ("unit_cost", models.DecimalField(decimal_places=4, default=0, max_digits=14, verbose_name="coût unitaire")),
                ("value", models.DecimalField(decimal_places=3, default=0, max_digits=16, verbose_name="valeur")),
                ("stock_after", models.DecimalField(decimal_places=3, max_digits=12, verbose_name="stock après (magasin)")),
                ("average_cost_after", models.DecimalField(decimal_places=4, max_digits=14, verbose_name="CMP après")),
                ("moved_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date")),
                ("reason", models.CharField(blank=True, max_length=255, verbose_name="motif")),
                ("document", models.CharField(blank=True, help_text="N° de bon de livraison, de facture, de bon de sortie…", max_length=100, verbose_name="document associé")),
                ("count", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="movements", to="inventory.stockcount")),
                ("equipment", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="assets.equipment", verbose_name="équipement")),
                ("item", models.ForeignKey(on_delete=PROTECT, related_name="movements", to="inventory.item", verbose_name="article")),
                ("request_line", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="movements", to="inventory.workorderpart")),
                ("supplier", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="inventory.supplier", verbose_name="fournisseur")),
                ("warehouse", models.ForeignKey(on_delete=PROTECT, related_name="movements", to="inventory.warehouse", verbose_name="magasin")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="stock_movements", to="workorders.workorder", verbose_name="OT")),
            ],
            options={"verbose_name": "mouvement de stock", "verbose_name_plural": "mouvements de stock", "ordering": ["-moved_at", "-pk"]},
        ),
        migrations.AddIndex(
            model_name="stockmovement",
            index=models.Index(fields=["item", "moved_at"], name="movement_item_date_idx"),
        ),
        migrations.CreateModel(
            name="EquipmentPart",
            fields=_base_fields() + [
                ("quantity", models.DecimalField(decimal_places=3, default=1, max_digits=12, verbose_name="quantité montée")),
                ("position", models.CharField(blank=True, max_length=150, verbose_name="repère / emplacement")),
                ("equipment", models.ForeignKey(on_delete=CASCADE, related_name="spare_parts", to="assets.equipment", verbose_name="équipement")),
                ("item", models.ForeignKey(on_delete=CASCADE, related_name="equipment_links", to="inventory.item", verbose_name="article")),
            ],
            options={"verbose_name": "pièce de l'équipement", "verbose_name_plural": "nomenclature des équipements", "ordering": ["item__reference"]},
        ),
        migrations.AddConstraint(
            model_name="equipmentpart",
            constraint=models.UniqueConstraint(fields=("tenant", "equipment", "item"), name="uniq_equipment_part"),
        ),
    ]
