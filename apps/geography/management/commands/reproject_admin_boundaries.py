"""Reproject stored admin boundaries that were imported in a projected CRS."""

from django.core.management.base import BaseCommand

from apps.geography.admin_boundary_service import _geometry_centroid
from apps.geography.models import AdminBoundary, Country
from apps.maps.crs_utils import ensure_wgs84_geometry, geometry_needs_reprojection


class Command(BaseCommand):
    help = "Reproject admin boundary geometries to WGS84 (fixes off-map village outlines)."

    def add_arguments(self, parser):
        parser.add_argument("--country", default="TZ")
        parser.add_argument("--level", type=int, default=4)
        parser.add_argument("--source-epsg", default="EPSG:21036")

    def handle(self, *args, **options):
        country = Country.objects.filter(code=options["country"].upper()).first()
        if not country:
            self.stderr.write(f"Country {options['country']} not found.")
            return

        level = options["level"]
        source_epsg = options["source_epsg"]
        qs = AdminBoundary.objects.filter(country=country, level=level)
        total = qs.count()
        fixed = 0
        skipped = 0

        self.stdout.write(f"Checking {total} boundaries (level {level}, {country.code})…")

        for boundary in qs.iterator(chunk_size=200):
            if not geometry_needs_reprojection(boundary.geometry):
                skipped += 1
                continue
            geometry = ensure_wgs84_geometry(
                boundary.geometry,
                source_epsg=source_epsg,
            )
            if not geometry:
                skipped += 1
                continue
            lat, lng = _geometry_centroid(geometry)
            boundary.geometry = geometry
            boundary.center_lat = lat
            boundary.center_lng = lng
            boundary.save(update_fields=["geometry", "center_lat", "center_lng"])
            fixed += 1
            if fixed % 500 == 0:
                self.stdout.write(f"  reprojected {fixed}…")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Reprojected {fixed}, already WGS84 {skipped}, total {total}."
            )
        )
