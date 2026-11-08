from django.db import migrations


class Migration(migrations.Migration):
    """La langue n'est plus réglée par utilisateur : elle est choisie à l'installation (EASYMAINT_LANGUAGE)."""

    dependencies = [
        ("accounts", "0002_user_language"),
    ]

    operations = [
        migrations.RemoveField(model_name="user", name="language"),
    ]
