import django.core.validators
import django.db.models.deletion
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


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        ("assets", "0002_location_kind_unite"),
        ("workforce", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PreventivePlan",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=200, verbose_name="intitulé")),
                ("operations", models.TextField(verbose_name="opération à effectuer")),
                ("instructions", models.TextField(blank=True, verbose_name="instructions techniques")),
                ("estimated_hours", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="temps estimé (h)")),
                ("priority", models.PositiveSmallIntegerField(choices=[(1, "P1 · Urgente"), (2, "P2 · Haute"), (3, "P3 · Normale"), (4, "P4 · Basse")], default=3, verbose_name="priorité des OT")),
                ("trigger_mode", models.CharField(choices=[("calendar", "Calendrier"), ("meter", "Compteur"), ("both", "Calendrier et compteur (le premier atteint)")], default="calendar", max_length=10, verbose_name="déclenchement")),
                ("period_value", models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1)], verbose_name="tous les")),
                ("period_unit", models.CharField(choices=[("day", "jour(s)"), ("week", "semaine(s)"), ("month", "mois"), ("year", "an(s)")], default="month", max_length=10, verbose_name="unité")),
                ("next_due_date", models.DateField(blank=True, null=True, verbose_name="prochaine échéance")),
                ("schedule_basis", models.CharField(choices=[("fixed", "Fixe : à partir de l'échéance prévue"), ("floating", "Glissante : à partir de la date de réalisation")], default="fixed", max_length=10, verbose_name="périodicité")),
                ("lead_days", models.PositiveSmallIntegerField(default=7, help_text="L'OT est créé ce nombre de jours avant l'échéance.", verbose_name="anticipation (jours)")),
                ("meter_interval", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, validators=[django.core.validators.MinValueValidator(0)], verbose_name="toutes les (unités du compteur)")),
                ("meter_lead", models.DecimalField(decimal_places=2, default=0, help_text="Par exemple 100 h : l'OT est créé 100 h avant le seuil.", max_digits=14, validators=[django.core.validators.MinValueValidator(0)], verbose_name="anticipation (unités du compteur)")),
                ("last_done_meter", models.DecimalField(blank=True, decimal_places=2, help_text="Laisser vide pour partir de la valeur actuelle du compteur.", max_digits=14, null=True, verbose_name="compteur au dernier entretien")),
                ("last_done_date", models.DateField(blank=True, null=True, verbose_name="dernière réalisation")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="preventive_plans", to="assets.equipment", verbose_name="équipement")),
                ("meter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="preventive_plans", to="assets.meter", verbose_name="compteur")),
                ("skills", models.ManyToManyField(blank=True, related_name="+", to="workforce.skill", verbose_name="compétences nécessaires")),
                ("team", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workforce.team", verbose_name="équipe")),
                ("technicians", models.ManyToManyField(blank=True, related_name="preventive_plans", to="workforce.technician", verbose_name="techniciens")),
            ],
            options={"verbose_name": "plan préventif", "verbose_name_plural": "plans préventifs", "ordering": ["code"]},
        ),
        migrations.AddConstraint(
            model_name="preventiveplan",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_plan_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="PlanChecklistItem",
            fields=_base_fields() + [
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("label", models.CharField(max_length=255, verbose_name="point de contrôle")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checklist", to="preventive.preventiveplan")),
            ],
            options={"verbose_name": "point de contrôle du plan", "verbose_name_plural": "check-list du plan", "ordering": ["position", "pk"]},
        ),
        migrations.CreateModel(
            name="PlanPart",
            fields=_base_fields() + [
                ("reference", models.CharField(blank=True, max_length=60, verbose_name="référence")),
                ("designation", models.CharField(max_length=200, verbose_name="désignation")),
                ("quantity", models.DecimalField(decimal_places=3, default=1, max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="quantité")),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parts", to="preventive.preventiveplan")),
            ],
            options={"verbose_name": "pièce prévue", "verbose_name_plural": "pièces prévues", "ordering": ["pk"]},
        ),
    ]
