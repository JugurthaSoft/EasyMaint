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
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Skill",
            fields=_base_fields() + [
                ("code", models.CharField(max_length=30, verbose_name="code")),
                ("name", models.CharField(max_length=100, verbose_name="nom")),
            ],
            options={"verbose_name": "compétence", "verbose_name_plural": "compétences", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="skill",
            constraint=models.UniqueConstraint(fields=("tenant", "code"), name="uniq_skill_code_per_tenant"),
        ),
        migrations.CreateModel(
            name="Team",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=100, verbose_name="nom")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
            ],
            options={"verbose_name": "équipe", "verbose_name_plural": "équipes", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="team",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="uniq_team_name_per_tenant"),
        ),
        migrations.CreateModel(
            name="Technician",
            fields=_base_fields() + [
                ("employee_number", models.CharField(max_length=30, verbose_name="matricule")),
                ("first_name", models.CharField(max_length=100, verbose_name="prénom")),
                ("last_name", models.CharField(max_length=100, verbose_name="nom")),
                ("function", models.CharField(blank=True, max_length=100, verbose_name="fonction")),
                ("specialty", models.CharField(blank=True, max_length=100, verbose_name="spécialité")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="téléphone")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("hourly_rate", models.DecimalField(decimal_places=3, default=0, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name="coût horaire")),
                ("overtime_rate", models.DecimalField(decimal_places=3, default=0, help_text="Laisser à 0 pour appliquer le coût horaire normal.", max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name="coût horaire heures supplémentaires")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
                ("skills", models.ManyToManyField(blank=True, related_name="technicians", to="workforce.skill", verbose_name="compétences")),
                ("team", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="members", to="workforce.team", verbose_name="équipe")),
                ("user", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="technician", to=settings.AUTH_USER_MODEL, verbose_name="compte utilisateur")),
            ],
            options={"verbose_name": "technicien", "verbose_name_plural": "techniciens", "ordering": ["last_name", "first_name"]},
        ),
        migrations.AddConstraint(
            model_name="technician",
            constraint=models.UniqueConstraint(fields=("tenant", "employee_number"), name="uniq_technician_number_per_tenant"),
        ),
        migrations.AddField(
            model_name="team",
            name="leader",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="workforce.technician", verbose_name="chef d'équipe"),
        ),
        migrations.CreateModel(
            name="Contractor",
            fields=_base_fields() + [
                ("name", models.CharField(max_length=150, verbose_name="raison sociale")),
                ("contact_name", models.CharField(blank=True, max_length=150, verbose_name="contact")),
                ("phone", models.CharField(blank=True, max_length=30, verbose_name="téléphone")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("specialties", models.CharField(blank=True, max_length=200, verbose_name="spécialités")),
                ("hourly_rate", models.DecimalField(decimal_places=3, default=0, max_digits=10, verbose_name="taux horaire indicatif")),
                ("notes", models.TextField(blank=True, verbose_name="notes")),
                ("is_active", models.BooleanField(default=True, verbose_name="actif")),
            ],
            options={"verbose_name": "sous-traitant", "verbose_name_plural": "sous-traitants", "ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="contractor",
            constraint=models.UniqueConstraint(fields=("tenant", "name"), name="uniq_contractor_name_per_tenant"),
        ),
    ]
