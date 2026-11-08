import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardLayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("blocks", models.JSONField(blank=True, default=list, verbose_name="blocs")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="dashboard_layout", to=settings.AUTH_USER_MODEL, verbose_name="utilisateur")),
            ],
            options={"verbose_name": "présentation de l'accueil", "verbose_name_plural": "présentations de l'accueil"},
        ),
    ]
