import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.imports.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DataImport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("kind", models.CharField(choices=[("equipements", "Équipements"), ("fournisseurs", "Fournisseurs"), ("articles", "Articles"), ("historique", "Historique de maintenance")], max_length=20, verbose_name="type")),
                ("file", models.FileField(upload_to=apps.imports.models.data_import_upload_to, verbose_name="fichier")),
                ("original_name", models.CharField(max_length=255, verbose_name="nom du fichier")),
                ("update_existing", models.BooleanField(default=False, verbose_name="mettre à jour les fiches existantes")),
                ("status", models.CharField(choices=[("draft", "À valider"), ("done", "Importé"), ("cancelled", "Abandonné")], default="draft", max_length=10, verbose_name="statut")),
                ("total_rows", models.PositiveIntegerField(default=0, verbose_name="lignes lues")),
                ("created_count", models.PositiveIntegerField(default=0, verbose_name="créées")),
                ("updated_count", models.PositiveIntegerField(default=0, verbose_name="mises à jour")),
                ("skipped", models.PositiveIntegerField(default=0, verbose_name="ignorées")),
                ("rejected", models.PositiveIntegerField(default=0, verbose_name="refusées")),
                ("errors", models.JSONField(blank=True, default=list, verbose_name="erreurs")),
                ("imported_at", models.DateTimeField(blank=True, null=True, verbose_name="importé le")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
            ],
            options={"verbose_name": "import de données", "verbose_name_plural": "imports de données", "ordering": ["-created_at"]},
        ),
    ]
