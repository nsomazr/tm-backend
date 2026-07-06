from django.core.management.base import BaseCommand

from apps.geography.admin_boundary_service import import_country_boundaries
from apps.geography.models import AdminBoundary, Country


class Command(BaseCommand):
    help = "Import administrative boundaries (GADM GeoJSON or built-in presets) for a country"

    def add_arguments(self, parser):
        parser.add_argument("--country", default="TZ", help="ISO country code (TZ, KE, UG)")
        parser.add_argument(
            "--levels",
            default="0,1,2",
            help="Comma-separated admin levels to import (0=country, 1=region, 2=district)",
        )
        parser.add_argument(
            "--no-presets",
            action="store_true",
            help="Do not fall back to preset geometries when GADM files are missing",
        )

    def handle(self, *args, **options):
        code = options["country"].upper()
        if not Country.objects.filter(code=code).exists():
            self.stderr.write(self.style.ERROR(f"Country {code} not found. Run seed_data first."))
            return

        levels = [int(x.strip()) for x in options["levels"].split(",") if x.strip().isdigit()]
        results = import_country_boundaries(
            code,
            levels=levels,
            source=AdminBoundary.Source.GADM,
            use_presets_if_missing=not options["no_presets"],
        )
        for level, count in sorted(results.items()):
            label = {0: "country", 1: "region", 2: "district"}.get(level, str(level))
            self.stdout.write(self.style.SUCCESS(f"  ADM{level} ({label}): {count} features"))
        self.stdout.write(self.style.SUCCESS(f"Done importing boundaries for {code}"))
