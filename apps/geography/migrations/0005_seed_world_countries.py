from django.db import migrations


def seed_world_countries(apps, schema_editor):
    Country = apps.get_model("geography", "Country")
    from apps.geography.country_geo import preset_for_code
    from apps.geography.world_countries import WORLD_COUNTRIES

    for code, name in WORLD_COUNTRIES:
        preset = preset_for_code(code)
        defaults = {
            "name": name,
            "name_sw": name,
            "is_active": True,
        }
        if preset:
            defaults.update(
                {
                    "center_lat": preset["center_lat"],
                    "center_lng": preset["center_lng"],
                    "default_zoom": preset["default_zoom"],
                    "bounds": preset["bounds"],
                    "boundary": preset["boundary"],
                }
            )
        Country.objects.get_or_create(code=code, defaults=defaults)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0004_alter_adminboundary_level"),
    ]

    operations = [
        migrations.RunPython(seed_world_countries, noop),
    ]
