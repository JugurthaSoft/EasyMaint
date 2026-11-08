from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="raison sociale")),
                ("code", models.SlugField(help_text="Identifiant court, utilisé comme sous-domaine en mode SaaS.", unique=True, verbose_name="code")),
                ("currency_code", models.CharField(default="TND", max_length=3, verbose_name="devise")),
                ("currency_decimals", models.PositiveSmallIntegerField(default=3, verbose_name="décimales de la devise")),
                ("time_zone", models.CharField(default="Africa/Tunis", max_length=64, verbose_name="fuseau horaire")),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créée le")),
            ],
            options={"verbose_name": "entreprise", "verbose_name_plural": "entreprises", "ordering": ["name"]},
        ),
    ]
