"""Hide catalog minerals that have no uploaded map geometry."""

from django.db import migrations


def deactivate_unmapped_minerals(apps, schema_editor):
    Mineral = apps.get_model("minerals", "Mineral")
    MapLayer = apps.get_model("maps", "MapLayer")
    MapFeature = apps.get_model("maps", "MapFeature")

    active_layer_ids = MapFeature.objects.filter(is_active=True).values_list("layer_id", flat=True).distinct()
    mineral_ids_with_uploads = set(
        MapLayer.objects.filter(id__in=active_layer_ids, is_active=True).values_list(
            "mineral_id", flat=True
        )
    )

    for mineral in Mineral.objects.all():
        should_be_active = mineral.id in mineral_ids_with_uploads
        if mineral.is_active != should_be_active:
            mineral.is_active = should_be_active
            mineral.save(update_fields=["is_active"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("minerals", "0001_initial"),
        ("maps", "0004_delete_inactive_empty_layers"),
    ]

    operations = [
        migrations.RunPython(deactivate_unmapped_minerals, noop),
    ]
