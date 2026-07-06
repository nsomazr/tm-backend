from django.db import migrations

DEMO_LINE_SLUGS = ("main-structures", "linear-structures")


def deactivate_demo_line_layers(apps, schema_editor):
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    demo_layers = MapLayer.objects.filter(slug__in=DEMO_LINE_SLUGS)
    MapFeature.objects.filter(layer__in=demo_layers, is_active=True).update(is_active=False)
    demo_layers.update(is_active=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(deactivate_demo_line_layers, noop),
    ]
