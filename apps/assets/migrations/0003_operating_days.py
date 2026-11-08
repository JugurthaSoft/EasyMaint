import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assets", "0002_location_kind_unite")]

    operations = [
        migrations.AddField(
            model_name="equipment",
            name="operating_days_per_week",
            field=models.PositiveSmallIntegerField(
                default=6,
                help_text="Du lundi au samedi pour 6 ; utilisé avec les heures requises pour le temps requis (MTBF, disponibilité).",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(7)],
                verbose_name="jours de fonctionnement par semaine",
            ),
        ),
    ]
