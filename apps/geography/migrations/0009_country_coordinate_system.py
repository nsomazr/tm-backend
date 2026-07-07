from django.db import migrations, models


def copy_platform_crs_to_tanzania(apps, schema_editor):
    Country = apps.get_model("geography", "Country")
    MapPlatformSettings = apps.get_model("maps", "MapPlatformSettings")
    crs = "arc1960"
    try:
        solo = MapPlatformSettings.objects.get(pk=1)
        if solo.coordinate_system:
            crs = solo.coordinate_system
    except MapPlatformSettings.DoesNotExist:
        pass
    Country.objects.filter(code="TZ").update(coordinate_system=crs)


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0008_boundary_geology"),
        ("maps", "0008_mapplatformsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="country",
            name="coordinate_system",
            field=models.CharField(
                default="arc1960",
                help_text="Default map coordinate reference system for this country.",
                max_length=32,
            ),
        ),
        migrations.RunPython(copy_platform_crs_to_tanzania, migrations.RunPython.noop),
    ]
