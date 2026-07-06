from django.db import migrations

PLACEHOLDER_SLUGS = (
    "main-structures",
    "linear-structures",
    "gold-priority-2",
    "gold-priority-3",
    "gold-priority-4",
    "graphite-zones",
    "tanzanite-zones",
    "sample-prospects",
    "demo-polygons",
)


def deactivate_placeholder_layers(apps, schema_editor):
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    name_q = None
    for term in ("gold priority", "structures", "graphite zones", "tanzanite zones"):
        clause = MapLayer.objects.filter(name__icontains=term)
        name_q = clause if name_q is None else name_q | clause

    layers = MapLayer.objects.filter(slug__in=PLACEHOLDER_SLUGS)
    if name_q is not None:
        layers = layers | name_q

    layer_ids = list(layers.values_list("id", flat=True).distinct())
    if not layer_ids:
        return

    MapFeature.objects.filter(layer_id__in=layer_ids, is_active=True).update(is_active=False)
    MapLayer.objects.filter(id__in=layer_ids, is_active=True).update(is_active=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0008_mapplatformsettings"),
    ]

    operations = [
        migrations.RunPython(deactivate_placeholder_layers, noop),
    ]
