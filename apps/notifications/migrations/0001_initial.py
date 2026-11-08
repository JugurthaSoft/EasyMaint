import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0003_audit_action_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("kind", models.CharField(choices=[("assigned", "OT affecté"), ("request", "Nouvelle demande"), ("alert", "Alerte conditionnelle"), ("part", "Demande de pièce"), ("to_validate", "OT à valider")], max_length=20, verbose_name="type")),
                ("title", models.CharField(max_length=200, verbose_name="titre")),
                ("body", models.CharField(blank=True, max_length=255, verbose_name="détail")),
                ("url", models.CharField(blank=True, max_length=300, verbose_name="lien")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="lue le")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("tenant", models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL, verbose_name="destinataire")),
            ],
            options={
                "verbose_name": "notification",
                "verbose_name_plural": "notifications",
                "ordering": ["-created_at", "-pk"],
                "indexes": [models.Index(fields=["user", "read_at"], name="notif_user_read_idx")],
            },
        ),
    ]
