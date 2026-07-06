from django.core.management.base import BaseCommand

from apps.geography.country_geo import preset_for_code
from apps.geography.models import Country
from apps.geography.world_countries import WORLD_COUNTRIES


class Command(BaseCommand):
    help = "Seed or update the world country catalog (ISO 3166-1 alpha-2)."

    def handle(self, *args, **options):
        created = 0
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
            _, was_created = Country.objects.get_or_create(code=code, defaults=defaults)
            if was_created:
                created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Country catalog ready ({len(WORLD_COUNTRIES)} entries, {created} new)."
            )
        )
