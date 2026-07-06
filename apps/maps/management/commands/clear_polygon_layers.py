import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.maps.models import MapFeature, MapLayer


class Command(BaseCommand):
    help = (
        "Remove demo polygon and line map layers, clear their features, "
        "and delete the bundled sample-data folder."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hard-delete",
            action="store_true",
            help="Permanently delete demo features instead of soft-deactivating them.",
        )

    def handle(self, *args, **options):
        demo_types = (MapLayer.LayerType.POLYGON, MapLayer.LayerType.LINE)
        demo_layers = MapLayer.objects.filter(layer_type__in=demo_types)
        layer_count = demo_layers.count()
        if layer_count == 0:
            self.stdout.write(self.style.SUCCESS("No demo polygon or line map layers found."))
            return

        feature_qs = MapFeature.objects.filter(layer__in=demo_layers)
        feature_count = feature_qs.count()

        if options["hard_delete"]:
            deleted_features, _ = feature_qs.delete()
            self.stdout.write(f"Deleted {deleted_features} demo feature row(s).")
        else:
            feature_qs.update(is_active=False)
            self.stdout.write(f"Deactivated {feature_count} demo feature(s).")

        demo_layers.update(is_active=False)

        sample_data_dir = Path(settings.BASE_DIR) / "sample_data"
        if sample_data_dir.exists():
            shutil.rmtree(sample_data_dir)
            self.stdout.write(self.style.WARNING(f"Deleted sample data directory: {sample_data_dir}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Deactivated {layer_count} demo layer(s). "
                "Upload new shapefiles via Admin → Layers."
            )
        )
