from django.db import migrations, models

from apps.minerals.color_utils import hex_to_rgba, normalize_hex


def backfill_color_rgba(apps, schema_editor):
    Mineral = apps.get_model("minerals", "Mineral")
    for mineral in Mineral.objects.all().iterator():
        hex_color = normalize_hex(mineral.color or "#E87722")
        Mineral.objects.filter(pk=mineral.pk).update(
            color=hex_color,
            color_rgba=hex_to_rgba(hex_color, 0.55),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("minerals", "0002_deactivate_unmapped_minerals"),
    ]

    operations = [
        migrations.AddField(
            model_name="mineral",
            name="color_rgba",
            field=models.CharField(
                blank=True,
                default="",
                help_text="RGBA fill derived from color hex (e.g. rgba(232,119,34,0.55))",
                max_length=40,
            ),
        ),
        migrations.RunPython(backfill_color_rgba, migrations.RunPython.noop),
    ]
