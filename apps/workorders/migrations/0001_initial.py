import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

PRIORITIES = [(1, "P1 · Urgente"), (2, "P2 · Haute"), (3, "P3 · Normale"), (4, "P4 · Basse")]


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
            name="FailureCode",
            fields=_base_fields() + [
                ("kind", models.CharField(choices=[("mode", "Mode de défaillance"), ("cause", "Cause"), ("remedy", "Remède")], max_length=10, verbose_name="type")),
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=150, verbose_name="libellé")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
            ],
            options={"verbose_name": "code de défaillance", "verbose_name_plural": "codes de défaillance", "ordering": ["kind", "name"]},
        ),
        migrations.AddConstraint(
            model_name="failurecode",
            constraint=models.UniqueConstraint(fields=("tenant", "kind", "code"), name="uniq_failure_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="WorkOrder",
            fields=_base_fields() + [
                ("number", models.CharField(editable=False, max_length=20, verbose_name="numéro")),
                ("kind", models.CharField(choices=[("corrective", "Correctif"), ("preventive", "Préventif"), ("conditional", "Conditionnel"), ("improvement", "Amélioratif")], default="corrective", max_length=20, verbose_name="type")),
                ("title", models.CharField(max_length=200, verbose_name="intitulé")),
                ("description", models.TextField(blank=True, verbose_name="description")),
                ("priority", models.PositiveSmallIntegerField(choices=PRIORITIES, default=3, verbose_name="priorité")),
                ("status", models.CharField(choices=[("to_plan", "À planifier"), ("assigned", "Affecté"), ("in_progress", "En cours"), ("waiting_parts", "En attente de pièces"), ("waiting_external", "En attente d'intervention externe"), ("done", "Terminé"), ("validated", "Validé"), ("cancelled", "Annulé")], default="to_plan", max_length=20, verbose_name="statut")),
                ("production_stopped", models.BooleanField(default=False, verbose_name="arrêt de production")),
                ("planned_date", models.DateField(blank=True, null=True, verbose_name="date prévue")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="échéance")),
                ("estimated_hours", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name="temps estimé (h)")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="début réel")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="fin réelle")),
                ("diagnosis", models.TextField(blank=True, verbose_name="diagnostic")),
                ("work_done", models.TextField(blank=True, verbose_name="travaux réalisés")),
                ("waiting_reason", models.CharField(blank=True, max_length=255, verbose_name="motif d'attente")),
                ("cancel_reason", models.CharField(blank=True, max_length=255, verbose_name="motif d'annulation")),
                ("validated_at", models.DateTimeField(blank=True, null=True, verbose_name="validé le")),
                ("labour_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="main-d'œuvre")),
                ("parts_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="pièces")),
                ("external_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="prestations externes")),
                ("other_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="autres dépenses")),
                ("total_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="coût total")),
                ("contractor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="workforce.contractor", verbose_name="sous-traitant")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_orders", to="assets.equipment", verbose_name="équipement")),
                ("failure_cause", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workorders.failurecode", verbose_name="cause")),
                ("failure_mode", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workorders.failurecode", verbose_name="mode de défaillance")),
                ("team", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="workforce.team", verbose_name="équipe")),
                ("technicians", models.ManyToManyField(blank=True, related_name="work_orders", to="workforce.technician", verbose_name="techniciens")),
                ("validated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="validé par")),
            ],
            options={"verbose_name": "ordre de travail", "verbose_name_plural": "ordres de travail", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="workorder",
            constraint=models.UniqueConstraint(fields=("tenant", "number"), name="uniq_work_order_number_per_tenant"),
        ),
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "status"], name="wo_status_idx")),
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "equipment"], name="wo_equipment_idx")),
        migrations.CreateModel(
            name="WorkRequest",
            fields=_base_fields() + [
                ("number", models.CharField(editable=False, max_length=20, verbose_name="numéro")),
                ("description", models.TextField(verbose_name="description du problème")),
                ("priority", models.PositiveSmallIntegerField(choices=PRIORITIES, default=3, verbose_name="priorité")),
                ("production_stopped", models.BooleanField(default=False, verbose_name="la production est arrêtée")),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="déclarée le")),
                ("status", models.CharField(choices=[("new", "Nouvelle"), ("accepted", "Acceptée"), ("rejected", "Refusée")], default="new", max_length=20, verbose_name="statut")),
                ("decided_at", models.DateTimeField(blank=True, null=True, verbose_name="traitée le")),
                ("decision_note", models.CharField(blank=True, max_length=255, verbose_name="commentaire de décision")),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="traitée par")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="work_requests", to="assets.equipment", verbose_name="équipement")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="demandeur")),
                ("work_order", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="request", to="workorders.workorder", verbose_name="ordre de travail")),
            ],
            options={"verbose_name": "demande d'intervention", "verbose_name_plural": "demandes d'intervention", "ordering": ["-requested_at"]},
        ),
        migrations.AddConstraint(
            model_name="workrequest",
            constraint=models.UniqueConstraint(fields=("tenant", "number"), name="uniq_work_request_number_per_tenant"),
        ),
        migrations.CreateModel(
            name="StatusLog",
            fields=_base_fields() + [
                ("from_status", models.CharField(blank=True, max_length=20)),
                ("to_status", models.CharField(max_length=20)),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                ("comment", models.CharField(blank=True, max_length=255)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_logs", to="workorders.workorder")),
            ],
            options={"ordering": ["at", "pk"]},
        ),
        migrations.CreateModel(
            name="TimeEntry",
            fields=_base_fields() + [
                ("started_at", models.DateTimeField(verbose_name="début")),
                ("ended_at", models.DateTimeField(blank=True, null=True, verbose_name="fin")),
                ("hours", models.DecimalField(decimal_places=2, default=0, max_digits=7, verbose_name="heures")),
                ("is_overtime", models.BooleanField(default=False, verbose_name="heures supplémentaires")),
                ("hourly_rate", models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name="taux appliqué")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="commentaire")),
                ("technician", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="time_entries", to="workforce.technician", verbose_name="technicien")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="time_entries", to="workorders.workorder")),
            ],
            options={"verbose_name": "pointage", "verbose_name_plural": "pointages", "ordering": ["started_at"]},
        ),
        migrations.CreateModel(
            name="PartUsage",
            fields=_base_fields() + [
                ("reference", models.CharField(blank=True, max_length=60, verbose_name="référence")),
                ("designation", models.CharField(max_length=200, verbose_name="désignation")),
                ("quantity", models.DecimalField(decimal_places=3, default=1, max_digits=12, verbose_name="quantité")),
                ("unit_cost", models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="coût unitaire")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parts", to="workorders.workorder")),
            ],
            options={"verbose_name": "pièce utilisée", "verbose_name_plural": "pièces utilisées", "ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="Expense",
            fields=_base_fields() + [
                ("nature", models.CharField(choices=[("external", "Prestation externe"), ("rental", "Location de matériel"), ("other", "Autre dépense")], default="external", max_length=20, verbose_name="nature")),
                ("label", models.CharField(max_length=200, verbose_name="libellé")),
                ("supplier", models.CharField(blank=True, max_length=150, verbose_name="fournisseur")),
                ("amount", models.DecimalField(decimal_places=3, max_digits=14, verbose_name="montant")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="workorders.workorder")),
            ],
            options={"verbose_name": "dépense", "verbose_name_plural": "dépenses", "ordering": ["pk"]},
        ),
        migrations.CreateModel(
            name="ChecklistItem",
            fields=_base_fields() + [
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("label", models.CharField(max_length=255, verbose_name="point de contrôle")),
                ("is_done", models.BooleanField(default=False, verbose_name="fait")),
                ("comment", models.CharField(blank=True, max_length=255, verbose_name="commentaire")),
                ("work_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="checklist", to="workorders.workorder")),
            ],
            options={"verbose_name": "point de contrôle", "verbose_name_plural": "check-list", "ordering": ["position", "pk"]},
        ),
        migrations.CreateModel(
            name="Downtime",
            fields=_base_fields() + [
                ("started_at", models.DateTimeField(verbose_name="début de l'arrêt")),
                ("ended_at", models.DateTimeField(blank=True, null=True, verbose_name="fin de l'arrêt")),
                ("production_stopped", models.BooleanField(default=True, verbose_name="arrêt de production")),
                ("origin", models.CharField(choices=[("failure", "Panne"), ("preventive", "Maintenance planifiée"), ("other", "Autre")], default="failure", max_length=20, verbose_name="origine")),
                ("equipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="downtimes", to="assets.equipment", verbose_name="équipement")),
                ("work_order", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="downtimes", to="workorders.workorder")),
                ("work_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="downtimes", to="workorders.workrequest")),
            ],
            options={"verbose_name": "arrêt machine", "verbose_name_plural": "arrêts machine", "ordering": ["-started_at"]},
        ),
        migrations.AddIndex(
            model_name="downtime",
            index=models.Index(fields=["equipment", "started_at"], name="downtime_equipment_idx"),
        ),
    ]
