import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.condition.models


def _base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
        ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
        ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("condition", "0001_initial"),
        ("core", "0002_sequence_audit_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportProfile",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("mapping", models.JSONField(blank=True, default=dict, verbose_name="correspondance des colonnes")),
            ],
            options={"verbose_name": "format d'import", "verbose_name_plural": "formats d'import", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="importprofile",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="uniq_import_profile_name_per_tenant"),
        ),
        migrations.CreateModel(
            name="MeasurementImport",
            fields=_base_fields() + [
                ("file", models.FileField(upload_to=apps.condition.models.import_upload_to, verbose_name="fichier")),
                ("original_name", models.CharField(max_length=255, verbose_name="nom du fichier")),
                ("mapping", models.JSONField(blank=True, default=dict, verbose_name="correspondance des colonnes")),
                ("status", models.CharField(choices=[("draft", "À valider"), ("done", "Importé"), ("cancelled", "Abandonné")], default="draft", max_length=10, verbose_name="statut")),
                ("total_rows", models.PositiveIntegerField(default=0, verbose_name="lignes lues")),
                ("imported", models.PositiveIntegerField(default=0, verbose_name="mesures importées")),
                ("skipped", models.PositiveIntegerField(default=0, verbose_name="doublons ignorés")),
                ("rejected", models.PositiveIntegerField(default=0, verbose_name="lignes refusées")),
                ("sessions_created", models.PositiveIntegerField(default=0, verbose_name="tournées créées")),
                ("errors", models.JSONField(blank=True, default=list, verbose_name="erreurs")),
                ("imported_at", models.DateTimeField(blank=True, null=True, verbose_name="importé le")),
                ("profile", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="imports", to="condition.importprofile", verbose_name="format")),
            ],
            options={"verbose_name": "import de mesures", "verbose_name_plural": "imports de mesures", "ordering": ["-created_at"]},
        ),
        migrations.AddField(
            model_name="measurementsession",
            name="source_import",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sessions", to="condition.measurementimport", verbose_name="import d'origine"),
        ),
        migrations.AddField(
            model_name="measurementsession",
            name="source_api",
            field=models.BooleanField(default=False, verbose_name="reçue par l'API"),
        ),
    ]
