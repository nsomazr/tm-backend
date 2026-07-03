from django.core.management.base import BaseCommand
from django.db import transaction

from apps.geography.sample_prospects import SAMPLE_LAYER_FEATURES
from apps.maps.models import LayerVersion, MapFeature, MapLayer
from apps.maps.tasks import _extract_point_coords, import_features_for_layer


class Command(BaseCommand):
    help = "Remove all map prospects and load regional sample data per layer"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="Do not delete existing features before loading",
        )

    def handle(self, *args, **options):
        if not options["keep_existing"]:
            deleted, _ = MapFeature.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Removed {deleted} existing features"))

        loaded = 0
        for slug, feature_defs in SAMPLE_LAYER_FEATURES.items():
            layer = MapLayer.objects.filter(slug=slug, is_active=True).first()
            if not layer:
                self.stdout.write(self.style.WARNING(f"Layer {slug} not found, skipping"))
                continue

            geojson_features = [
                {
                    "type": "Feature",
                    "geometry": fd["geometry"],
                    "properties": fd["properties"],
                }
                for fd in feature_defs
            ]

            with transaction.atomic():
                layer.features.filter(is_active=True).update(is_active=False)
                count = import_features_for_layer(layer, geojson_features, source=f"sample:{slug}")
                layer.current_version += 1
                layer.save(update_fields=["current_version"])
                LayerVersion.objects.create(
                    layer=layer,
                    version_number=layer.current_version,
                    changelog=f"Loaded regional sample data ({count} features)",
                    feature_count=count,
                )
            loaded += count
            self.stdout.write(f"  {slug}: {count} features in {feature_defs[0]['properties'].get('region', '?')}")

        self.stdout.write(self.style.SUCCESS(f"Loaded {loaded} sample prospects across {len(SAMPLE_LAYER_FEATURES)} layers"))
