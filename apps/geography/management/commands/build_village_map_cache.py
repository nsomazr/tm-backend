from django.core.management.base import BaseCommand

from apps.geography.boundary_map_cache import build_village_display_cache, village_cache_path
from apps.geography.models import Country


class Command(BaseCommand):
    help = "Build on-disk gzip cache for village map boundaries (TZ level 4)."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="TZ")

    def handle(self, *args, **options):
        country = Country.objects.filter(code=options["country"].upper()).first()
        if not country:
            self.stderr.write(f"Country {options['country']} not found.")
            return

        self.stdout.write(f"Building village map cache for {country.code}…")
        count = build_village_display_cache(country)
        path = village_cache_path(country.code)
        size_mb = path.stat().st_size / (1024 * 1024)
        self.stdout.write(
            self.style.SUCCESS(
                f"Cached {count} villages → {path} ({size_mb:.1f} MB compressed)"
            )
        )
