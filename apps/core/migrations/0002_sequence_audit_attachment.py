import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.core.models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("doc_type", models.CharField(max_length=10, verbose_name="type de document")),
                ("year", models.PositiveSmallIntegerField(verbose_name="année")),
                ("last_number", models.PositiveIntegerField(default=0, verbose_name="dernier numéro")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
            ],
            options={"verbose_name": "séquence de numérotation"},
        ),
        migrations.AddConstraint(
            model_name="documentsequence",
            constraint=models.UniqueConstraint(fields=("tenant", "doc_type", "year"), name="uniq_sequence_per_tenant_type_year"),
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(blank=True, max_length=150, verbose_name="identifiant")),
                ("action", models.CharField(choices=[("login", "Connexion"), ("login_failed", "Échec de connexion"), ("logout", "Déconnexion"), ("create", "Création"), ("update", "Modification"), ("delete", "Suppression"), ("export", "Export")], max_length=20, verbose_name="action")),
                ("object_type", models.CharField(blank=True, max_length=100, verbose_name="type d'objet")),
                ("object_id", models.CharField(blank=True, max_length=64, verbose_name="identifiant de l'objet")),
                ("object_repr", models.CharField(blank=True, max_length=255, verbose_name="objet")),
                ("changes", models.JSONField(blank=True, default=dict, verbose_name="modifications")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="adresse IP")),
                ("at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name="date")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "entrée du journal", "verbose_name_plural": "journal d'audit", "ordering": ["-at"]},
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["tenant", "object_type", "object_id"], name="audit_object_idx"),
        ),
        migrations.CreateModel(
            name="Attachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("object_id", models.PositiveBigIntegerField()),
                ("file", models.FileField(upload_to=apps.core.models.attachment_upload_to, validators=[apps.core.models.validate_attachment], verbose_name="fichier")),
                ("original_name", models.CharField(max_length=255, verbose_name="nom du fichier")),
                ("title", models.CharField(blank=True, max_length=200, verbose_name="titre")),
                ("category", models.CharField(choices=[("technical", "Documentation technique"), ("plan", "Plan ou schéma"), ("photo", "Photo"), ("photo_before", "Photo avant intervention"), ("photo_after", "Photo après intervention"), ("report", "Rapport"), ("other", "Autre")], default="technical", max_length=20, verbose_name="catégorie")),
                ("size", models.PositiveBigIntegerField(default=0, verbose_name="taille (octets)")),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="contenttypes.contenttype")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
            ],
            options={"verbose_name": "pièce jointe", "verbose_name_plural": "pièces jointes", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="attachment",
            index=models.Index(fields=["tenant", "content_type", "object_id"], name="attachment_object_idx"),
        ),
    ]
