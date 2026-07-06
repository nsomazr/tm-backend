import os

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.geography.sample_prospects import SAMPLE_LAYER_FEATURES
from apps.maps.models import MapLayer
from apps.maps.shapefile_utils import write_line_shapefile_zip, write_polygon_shapefile_zip


class Command(BaseCommand):
    help = "Generate sample shapefile ZIPs for each map layer in sample_data/shapefiles/"

    def handle(self, *args, **options):
        out_dir = os.path.join(settings.BASE_DIR, "sample_data", "shapefiles")
        os.makedirs(out_dir, exist_ok=True)

        for slug, features in SAMPLE_LAYER_FEATURES.items():
            layer = MapLayer.objects.filter(slug=slug, is_active=True).first()
            if not layer:
                self.stdout.write(self.style.WARNING(f"Skipping {slug}: layer not found"))
                continue
            if layer.layer_type == MapLayer.LayerType.POLYGON:
                self.stdout.write(self.style.WARNING(f"Skipping {slug}: polygon layers are not seeded"))
                continue

            out_path = os.path.join(out_dir, f"{slug}.zip")
            if layer.layer_type == "line":
                write_line_shapefile_zip(features, out_path)
            else:
                write_polygon_shapefile_zip(features, out_path)

            self.stdout.write(self.style.SUCCESS(f"Created {out_path} ({len(features)} features)"))

        readme = os.path.join(out_dir, "README.md")
        with open(readme, "w") as f:
            f.write(
                "# Sample prospect shapefiles\n\n"
                "Each ZIP contains an ESRI shapefile for one map layer.\n"
                "Upload via Admin → Layers → Import Shapefile / ZIP.\n\n"
                "Layers are placed in distinct Tanzania regions to avoid overlap on the map.\n"
            )
        self.stdout.write(self.style.SUCCESS(f"Done. Files in {out_dir}"))
