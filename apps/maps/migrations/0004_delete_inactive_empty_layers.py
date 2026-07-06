from django.db import migrations


def delete_inactive_empty_layers(apps, schema_editor):
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    layer_ids_with_features = set(
        MapFeature.objects.filter(is_active=True).values_list("layer_id", flat=True)
    )
    stale = MapLayer.objects.filter(is_active=False).exclude(id__in=layer_ids_with_features)
    stale.delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("maps", "0003_deactivate_layers_without_features"),
    ]

    operations = [
        migrations.RunPython(delete_inactive_empty_layers, noop),
    ]
