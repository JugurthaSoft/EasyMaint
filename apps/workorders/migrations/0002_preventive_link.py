import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workorders", "0001_initial"),
        ("preventive", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="original_due_date",
            field=models.DateField(blank=True, help_text="Conservée lors d'un report, pour mesurer le respect du planning.", null=True, verbose_name="échéance d'origine"),
        ),
        migrations.AddField(
            model_name="workorder",
            name="preventive_plan",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_orders", to="preventive.preventiveplan", verbose_name="plan préventif"),
        ),
    ]
