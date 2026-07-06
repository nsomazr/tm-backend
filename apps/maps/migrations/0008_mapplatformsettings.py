from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0007_reactivate_layers_with_features"),
    ]

    operations = [
        migrations.CreateModel(
            name="MapPlatformSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("coordinate_system", models.CharField(default="arc1960", max_length=32)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Map platform settings",
                "verbose_name_plural": "Map platform settings",
            },
        ),
    ]
