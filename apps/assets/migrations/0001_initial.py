import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.assets.models


def _base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
        ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
        ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
    ]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Location",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("kind", models.CharField(choices=[("site", "Usine"), ("workshop", "Atelier"), ("line", "Ligne de production"), ("zone", "Zone")], default="workshop", max_length=20, verbose_name="type")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="assets.location", verbose_name="parent")),
            ],
            options={"verbose_name": "localisation", "verbose_name_plural": "localisations", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_location_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="EquipmentFamily",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="assets.equipmentfamily", verbose_name="famille parente")),
            ],
            options={"verbose_name": "famille d'équipements", "verbose_name_plural": "familles d'équipements", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="equipmentfamily",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_family_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="Manufacturer",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("website", models.URLField(blank=True, verbose_name="site web")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="téléphone")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
            ],
            options={"verbose_name": "fabricant", "verbose_name_plural": "fabricants", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="manufacturer",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="uniq_manufacturer_name_per_tenant"),
        ),
        migrations.CreateModel(
            name="Equipment",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=40, verbose_name="code")),
                ("designation", models.CharField(max_length=200, verbose_name="désignation")),
                ("brand", models.CharField(blank=True, max_length=100, verbose_name="marque")),
                ("model", models.CharField(blank=True, max_length=100, verbose_name="modèle")),
                ("serial_number", models.CharField(blank=True, max_length=100, verbose_name="n° de série")),
                ("commissioning_date", models.DateField(blank=True, null=True, verbose_name="date de mise en service")),
                ("status", models.CharField(choices=[("in_service", "En service"), ("stopped", "Arrêté"), ("broken", "En panne"), ("retired", "Réformé")], default="in_service", max_length=20, verbose_name="état")),
                ("criticality", models.CharField(choices=[("A", "A — critique"), ("B", "B — importante"), ("C", "C — secondaire")], default="B", max_length=1, verbose_name="criticité")),
                ("photo", models.ImageField(blank=True, upload_to=apps.assets.models.equipment_photo_upload_to, verbose_name="photo")),
                ("required_hours_per_day", models.DecimalField(decimal_places=1, default=16, help_text="Temps d'ouverture prévu, utilisé pour la disponibilité.", max_digits=4, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(24)], verbose_name="heures requises par jour")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("qr_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("family", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="equipment", to="assets.equipmentfamily", verbose_name="famille")),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="equipment", to="assets.location", verbose_name="localisation")),
                ("manufacturer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="equipment", to="assets.manufacturer", verbose_name="fabricant")),
                ("parent", models.ForeignKey(blank=True, help_text="Renseigner pour un sous-équipement.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="children", to="assets.equipment", verbose_name="équipement parent")),
                ("responsible", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="responsable")),
            ],
            options={"verbose_name": "équipement", "verbose_name_plural": "équipements", "ordering": ["code"]},
        ),
        migrations.AddConstraint(
            model_name="equipment",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_equipment_code_per_tenant"),
        ),
        migrations.AddIndex(
            model_name="equipment",
            index=models.Index(fields=["tenant", "status"], name="equipment_status_idx"),
        ),
        migrations.CreateModel(
            name="Meter",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=100, verbose_name="nom")),
                ("kind", models.CharField(choices=[("hours", "Heures de fonctionnement"), ("cycles", "Nombre de cycles"), ("distance", "Kilométrage"), ("custom", "Personnalisé")], default="hours", max_length=20, verbose_name="type")),
                ("unit", models.CharField(blank=True, max_length=20, verbose_name="unité")),
                ("is_cumulative", models.BooleanField(default=True, help_text="Un compteur cumulatif ne peut jamais diminuer.", verbose_name="cumulatif")),
                ("current_value", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="valeur actuelle")),
                ("last_reading_at", models.DateTimeField(blank=True, null=True, verbose_name="dernier relevé")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meters", to="assets.equipment", verbose_name="équipement")),
            ],
            options={"verbose_name": "compteur", "verbose_name_plural": "compteurs", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="meter",
            constraint=models.UniqueConstraint(fields=("equipment", "name"), name="uniq_meter_name_per_equipment"),
        ),
        migrations.CreateModel(
            name="MeterReading",
            fields=_base_fields() + [
                ("reading_at", models.DateTimeField(verbose_name="date du relevé")),
                ("value", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="valeur")),
                ("source", models.CharField(choices=[("manual", "Saisie"), ("workorder", "Ordre de travail"), ("import", "Import"), ("sensor", "Capteur")], default="manual", max_length=20, verbose_name="origine")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="commentaire")),
                ("meter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="readings", to="assets.meter", verbose_name="compteur")),
            ],
            options={"verbose_name": "relevé de compteur", "verbose_name_plural": "relevés de compteurs", "ordering": ["-reading_at"]},
        ),
        migrations.AddIndex(
            model_name="meterreading",
            index=models.Index(fields=["meter", "reading_at"], name="reading_meter_date_idx"),
        ),
    ]
