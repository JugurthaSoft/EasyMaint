import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.kpi.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("year", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(2000), django.core.validators.MaxValueValidator(2100)], verbose_name="année")),
                ("month", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)], verbose_name="mois")),
                ("file", models.FileField(upload_to=apps.kpi.models.report_upload_to, verbose_name="fichier")),
                ("generated_at", models.DateTimeField(auto_now=True, verbose_name="produit le")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("generated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="produit par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
            ],
            options={"verbose_name": "rapport mensuel", "verbose_name_plural": "rapports mensuels", "ordering": ["-year", "-month"]},
        ),
        migrations.AddConstraint(
            model_name="monthlyreport",
            constraint=models.UniqueConstraint(fields=("tenant", "year", "month"), name="uniq_monthly_report"),
        ),
    ]
