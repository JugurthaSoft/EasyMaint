from django.db import migrations, models


class Migration(migrations.Migration):
    """Index pour le contrôle des échecs de connexion (blocage après plusieurs essais)."""

    dependencies = [
        ("core", "0002_sequence_audit_attachment"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["action", "at"], name="audit_action_at_idx"),
        ),
    ]
