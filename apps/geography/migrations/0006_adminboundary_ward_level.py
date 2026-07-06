from django.db import migrations, models


def move_villages_to_level_4(apps, schema_editor):
    AdminBoundary = apps.get_model("geography", "AdminBoundary")
    AdminBoundary.objects.filter(level=3).update(level=4)


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0005_seed_world_countries"),
    ]

    operations = [
        migrations.RunPython(move_villages_to_level_4, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="adminboundary",
            name="level",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Country"),
                    (1, "Region"),
                    (2, "District"),
                    (3, "Ward"),
                    (4, "Village"),
                ]
            ),
        ),
    ]
