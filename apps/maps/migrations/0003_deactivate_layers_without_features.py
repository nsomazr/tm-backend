from django.db import migrations


def deactivate_layers_without_features(apps, schema_editor):
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    layer_ids_with_features = (
        MapFeature.objects.filter(is_active=True)
        .values_list("layer_id", flat=True)
        .distinct()
    )
    MapLayer.objects.exclude(id__in=layer_ids_with_features).update(is_active=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0002_deactivate_demo_line_layers"),
    ]

    operations = [
        migrations.RunPython(deactivate_layers_without_features, noop),
    ]
