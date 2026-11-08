"""Le niveau « Atelier » est renommé « Unité ». Seul le libellé change : les données existantes restent valides."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="location",
            name="kind",
            field=models.CharField(choices=[("site", "Usine"), ("workshop", "Unité"), ("line", "Ligne de production"), ("zone", "Zone")], default="workshop", max_length=20, verbose_name="type"),
        ),
    ]
