import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        ("assets", "0002_location_kind_unite"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Budget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("year", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(2000), django.core.validators.MaxValueValidator(2100)], verbose_name="année")),
                ("month_01", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="janvier")),
                ("month_02", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="février")),
                ("month_03", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="mars")),
                ("month_04", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="avril")),
                ("month_05", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="mai")),
                ("month_06", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="juin")),
                ("month_07", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="juillet")),
                ("month_08", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="août")),
                ("month_09", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="septembre")),
                ("month_10", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="octobre")),
                ("month_11", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="novembre")),
                ("month_12", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="décembre")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="assets.location", verbose_name="unité")),
            ],
            options={"verbose_name": "budget de maintenance", "verbose_name_plural": "budgets de maintenance", "ordering": ["year", "unit__name"]},
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.UniqueConstraint(fields=("tenant", "year", "unit"), name="uniq_budget_year_unit"),
        ),
    ]
