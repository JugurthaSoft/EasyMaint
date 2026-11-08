from django.db import migrations, models


class Migration(migrations.Migration):
    """Index pour accélérer les listes d'OT, les retards, les coûts et les indicateurs."""

    dependencies = [
        ("workorders", "0002_preventive_link"),
    ]

    operations = [
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "-created_at"], name="wo_created_idx")),
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "kind", "status"], name="wo_kind_status_idx")),
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "due_date"], name="wo_due_idx")),
        migrations.AddIndex(model_name="workorder", index=models.Index(fields=["tenant", "finished_at"], name="wo_finished_idx")),
        migrations.AddIndex(model_name="workrequest", index=models.Index(fields=["tenant", "status"], name="wr_status_idx")),
    ]
