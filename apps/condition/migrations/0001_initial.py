import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.condition.models

LEVELS = [("unknown", "Sans seuil"), ("normal", "Normal"), ("warning", "Attention"), ("alarm", "Alarme"), ("critical", "Critique")]
PRIORITIES = [(1, "P1 · Urgente"), (2, "P2 · Haute"), (3, "P3 · Normale"), (4, "P4 · Basse")]


def _base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
        ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
        ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
    ]


def _decimal(label):
    return models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True, verbose_name=label)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        ("assets", "0002_location_kind_unite"),
        ("workforce", "0001_initial"),
        ("workorders", "0002_preventive_link"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Parameter",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=120, verbose_name="nom")),
                ("unit", models.CharField(blank=True, max_length=20, verbose_name="unité")),
                ("category", models.CharField(choices=[("vibration", "Analyse vibratoire"), ("oil", "Analyse d'huile"), ("temperature", "Température"), ("pressure", "Pression"), ("flow", "Débit"), ("current", "Intensité électrique"), ("energy", "Consommation énergétique"), ("thickness", "Épaisseur"), ("other", "Autre")], default="other", max_length=20, verbose_name="catégorie")),
                ("direction", models.CharField(choices=[("rising", "Alerte si la valeur monte"), ("falling", "Alerte si la valeur baisse"), ("range", "Alerte hors d'une plage")], default="rising", max_length=10, verbose_name="sens d'alerte")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
            ],
            options={"verbose_name": "paramètre de mesure", "verbose_name_plural": "paramètres de mesure", "ordering": ["category", "name"]},
        ),
        migrations.AddConstraint(
            model_name="parameter",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_parameter_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="MeasurementPoint",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("position", models.CharField(blank=True, help_text="Par exemple : palier moteur côté accouplement.", max_length=200, verbose_name="emplacement")),
                ("direction", models.CharField(blank=True, choices=[("", "—"), ("H", "Horizontale"), ("V", "Verticale"), ("A", "Axiale")], default="", max_length=1, verbose_name="direction de mesure")),
                ("photo", models.ImageField(blank=True, upload_to=apps.condition.models.point_photo_upload_to, verbose_name="photo de l'emplacement")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="measurement_points", to="assets.equipment", verbose_name="équipement")),
                ("parameters", models.ManyToManyField(related_name="points", to="condition.parameter", verbose_name="paramètres mesurés")),
            ],
            options={"verbose_name": "point de mesure", "verbose_name_plural": "points de mesure", "ordering": ["code"]},
        ),
        migrations.AddConstraint(
            model_name="measurementpoint",
            constraint=models.UniqueConstraint(fields=("tenant", "equipment", "code"), name="uniq_point_code_per_equipment"),
        ),
        migrations.CreateModel(
            name="Threshold",
            fields=_base_fields() + [
                ("valid_from", models.DateField(default=django.utils.timezone.localdate, verbose_name="applicable à partir du")),
                ("warning_high", _decimal("attention (haut)")),
                ("alarm_high", _decimal("alarme (haut)")),
                ("critical_high", _decimal("critique (haut)")),
                ("warning_low", _decimal("attention (bas)")),
                ("alarm_low", _decimal("alarme (bas)")),
                ("critical_low", _decimal("critique (bas)")),
                ("source", models.CharField(choices=[("standard", "Norme"), ("manufacturer", "Constructeur"), ("laboratory", "Laboratoire"), ("experience", "Retour d'expérience"), ("other", "Autre")], default="manufacturer", max_length=20, verbose_name="source")),
                ("reference", models.CharField(blank=True, help_text="Norme, document constructeur, rapport…", max_length=200, verbose_name="référence")),
                ("parameter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="thresholds", to="condition.parameter", verbose_name="paramètre")),
                ("point", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="thresholds", to="condition.measurementpoint", verbose_name="point")),
            ],
            options={"verbose_name": "seuil", "verbose_name_plural": "seuils", "ordering": ["-valid_from", "-pk"]},
        ),
        migrations.CreateModel(
            name="MeasurementSession",
            fields=_base_fields() + [
                ("kind", models.CharField(choices=[("vibration", "Analyse vibratoire"), ("oil", "Analyse d'huile"), ("inspection", "Contrôle / relevé")], default="inspection", max_length=20, verbose_name="type")),
                ("measured_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date et heure")),
                ("rotation_speed", models.DecimalField(blank=True, decimal_places=1, max_digits=8, null=True, verbose_name="vitesse de rotation (tr/min)")),
                ("load_condition", models.CharField(blank=True, max_length=150, verbose_name="régime de fonctionnement")),
                ("observations", models.TextField(blank=True, verbose_name="observations")),
                ("oil_type", models.CharField(blank=True, max_length=100, verbose_name="type d'huile")),
                ("oil_hours", models.DecimalField(blank=True, decimal_places=1, max_digits=10, null=True, verbose_name="heures de l'huile")),
                ("operating_hours", models.DecimalField(blank=True, decimal_places=1, max_digits=12, null=True, verbose_name="heures de fonctionnement")),
                ("laboratory", models.CharField(blank=True, max_length=150, verbose_name="laboratoire")),
                ("lab_report_number", models.CharField(blank=True, max_length=60, verbose_name="n° de rapport")),
                ("lab_conclusion", models.TextField(blank=True, verbose_name="conclusion du laboratoire")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="measurement_sessions", to="assets.equipment", verbose_name="équipement")),
                ("technician", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workforce.technician", verbose_name="technicien")),
            ],
            options={"verbose_name": "tournée de mesures", "verbose_name_plural": "tournées de mesures", "ordering": ["-measured_at"]},
        ),
        migrations.CreateModel(
            name="Measurement",
            fields=_base_fields() + [
                ("value", models.DecimalField(decimal_places=4, max_digits=14, verbose_name="valeur")),
                ("level", models.CharField(choices=LEVELS, default="unknown", max_length=10, verbose_name="niveau")),
                ("measured_at", models.DateTimeField(verbose_name="date")),
                ("parameter", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="measurements", to="condition.parameter", verbose_name="paramètre")),
                ("point", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="measurements", to="condition.measurementpoint", verbose_name="point")),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="measurements", to="condition.measurementsession")),
                ("threshold", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="condition.threshold")),
            ],
            options={"verbose_name": "mesure", "verbose_name_plural": "mesures", "ordering": ["-measured_at", "-pk"]},
        ),
        migrations.AddIndex(
            model_name="measurement",
            index=models.Index(fields=["point", "parameter", "measured_at"], name="measure_series_idx"),
        ),
        migrations.CreateModel(
            name="TriggerRule",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=150, verbose_name="nom")),
                ("min_level", models.CharField(choices=[("warning", "Attention"), ("alarm", "Alarme"), ("critical", "Critique")], default="alarm", max_length=10, verbose_name="à partir du niveau")),
                ("consecutive", models.PositiveSmallIntegerField(default=1, help_text="Nombre de mesures successives au moins à ce niveau avant d'agir.", validators=[django.core.validators.MinValueValidator(1)], verbose_name="mesures consécutives")),
                ("action", models.CharField(choices=[("request", "Créer une demande d'intervention"), ("work_order", "Créer un OT conditionnel")], default="request", max_length=20, verbose_name="action")),
                ("priority", models.PositiveSmallIntegerField(choices=PRIORITIES, default=2, verbose_name="priorité")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("equipment", models.ForeignKey(blank=True, help_text="Laisser vide pour appliquer la règle à tous les équipements.", null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="assets.equipment", verbose_name="équipement")),
                ("parameter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rules", to="condition.parameter", verbose_name="paramètre")),
            ],
            options={"verbose_name": "règle de déclenchement", "verbose_name_plural": "règles de déclenchement", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Alert",
            fields=_base_fields() + [
                ("level", models.CharField(choices=LEVELS, max_length=10, verbose_name="niveau")),
                ("max_level", models.CharField(choices=LEVELS, max_length=10, verbose_name="niveau le plus grave")),
                ("status", models.CharField(choices=[("open", "Ouverte"), ("acknowledged", "Acquittée"), ("closed", "Close")], default="open", max_length=15, verbose_name="statut")),
                ("opened_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="ouverte le")),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("comment", models.CharField(blank=True, max_length=255, verbose_name="commentaire")),
                ("acknowledged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("first_measurement", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="condition.measurement")),
                ("last_measurement", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="condition.measurement")),
                ("parameter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to="condition.parameter", verbose_name="paramètre")),
                ("point", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to="condition.measurementpoint", verbose_name="point")),
                ("rule", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="alerts", to="condition.triggerrule")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workorders.workorder")),
                ("work_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workorders.workrequest")),
            ],
            options={"verbose_name": "alerte", "verbose_name_plural": "alertes", "ordering": ["-opened_at"]},
        ),
        migrations.AddIndex(
            model_name="alert",
            index=models.Index(fields=["tenant", "status"], name="alert_status_idx"),
        ),
    ]
