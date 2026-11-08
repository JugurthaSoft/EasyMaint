import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("preventive", "0001_initial"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="planpart",
            name="item",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="inventory.item", verbose_name="article du magasin"),
        ),
    ]
