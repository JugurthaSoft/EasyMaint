import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def _base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
        ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
        ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
    ]


SET_NULL = django.db.models.deletion.SET_NULL


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("core", "0002_sequence_audit_attachment"),
        ("assets", "0002_location_kind_unite"),
        ("workorders", "0002_preventive_link"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="purchase_order",
            field=models.CharField(blank=True, help_text="Bon de commande émis par le service achats.", max_length=40, verbose_name="n° de bon de commande"),
        ),
        migrations.CreateModel(
            name="PurchaseRequest",
            fields=_base_fields() + [
                ("number", models.CharField(editable=False, max_length=20, verbose_name="numéro")),
                ("requested_on", models.DateField(default=django.utils.timezone.localdate, verbose_name="date")),
                ("reason", models.CharField(blank=True, help_text="Réapprovisionnement, réparation, amélioration…", max_length=255, verbose_name="motif")),
                ("needed_by", models.DateField(blank=True, null=True, verbose_name="date souhaitée")),
                ("is_urgent", models.BooleanField(default=False, verbose_name="urgent")),
                ("notes", models.TextField(blank=True, verbose_name="observations")),
                ("equipment", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="assets.equipment", verbose_name="équipement concerné")),
                ("supplier", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="purchase_requests", to="inventory.supplier", verbose_name="fournisseur suggéré")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="workorders.workorder", verbose_name="OT concerné")),
            ],
            options={"verbose_name": "demande d'achat", "verbose_name_plural": "demandes d'achat", "ordering": ["-requested_on", "-pk"]},
        ),
        migrations.CreateModel(
            name="PurchaseRequestLine",
            fields=_base_fields() + [
                ("reference", models.CharField(blank=True, max_length=80, verbose_name="référence")),
                ("designation", models.CharField(max_length=200, verbose_name="désignation")),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12, verbose_name="quantité")),
                ("unit", models.CharField(blank=True, max_length=20, verbose_name="unité")),
                ("estimated_price", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True, verbose_name="prix unitaire estimé HT")),
                ("position", models.PositiveSmallIntegerField(default=0, verbose_name="ordre")),
                ("item", models.ForeignKey(blank=True, null=True, on_delete=SET_NULL, related_name="+", to="inventory.item", verbose_name="article du magasin")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="inventory.purchaserequest")),
            ],
            options={"verbose_name": "ligne de demande d'achat", "verbose_name_plural": "lignes de demande d'achat", "ordering": ["position", "pk"]},
        ),
    ]
