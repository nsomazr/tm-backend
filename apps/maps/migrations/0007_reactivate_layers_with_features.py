from django.db import migrations


def reactivate_layers_with_features(apps, schema_editor):
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    layer_ids = (
        MapFeature.objects.filter(is_active=True)
        .values_list("layer_id", flat=True)
        .distinct()
    )
    MapLayer.objects.filter(id__in=layer_ids, is_active=False).update(is_active=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("maps", "0006_mapfeature_created_by"),
    ]

    operations = [
        migrations.RunPython(reactivate_layers_with_features, noop),
    ]
