from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="language",
            field=models.CharField(choices=[("fr", "Français"), ("en", "English")], default="fr", max_length=5, verbose_name="langue"),
        ),
    ]
