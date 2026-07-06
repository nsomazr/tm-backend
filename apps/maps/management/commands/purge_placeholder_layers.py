"""Deactivate or delete placeholder / demo map layers (Gold Priority, structures, etc.)."""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.maps.models import MapFeature, MapLayer

# Known demo slugs from early seeds and migrations.
PLACEHOLDER_SLUGS = frozenset(
    {
        "main-structures",
        "linear-structures",
        "gold-priority-2",
        "gold-priority-3",
        "gold-priority-4",
        "graphite-zones",
        "tanzanite-zones",
        "sample-prospects",
        "demo-polygons",
    }
)

# Name patterns for auto-created commodity placeholders without real uploads.
PLACEHOLDER_NAME_RE = re.compile(
    r"(gold\s+priority|structures|graphite\s+zones|tanzanite\s+zones|demo|sample|placeholder)",
    re.I,
)


class Command(BaseCommand):
    help = (
        "Deactivate placeholder map layers (Gold Priority, structures, empty demo zones). "
        "Real uploaded commodity layers are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hard-delete",
            action="store_true",
            help="Permanently delete matching layers and their features.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List matching layers without changing the database.",
        )
        parser.add_argument(
            "--include-empty",
            action="store_true",
            help="Also deactivate active layers with zero active features.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        hard_delete = options["hard_delete"]
        include_empty = options["include_empty"]

        slug_q = Q(slug__in=PLACEHOLDER_SLUGS)
        name_q = Q()
        for term in ("gold priority", "structures", "graphite zones", "tanzanite zones"):
            name_q |= Q(name__icontains=term) | Q(name_sw__icontains=term)

        qs = MapLayer.objects.filter(slug_q | name_q).distinct()

        if include_empty:
            from apps.maps.access import layers_with_mapped_data

            empty_ids = (
                MapLayer.objects.filter(is_active=True)
                .exclude(id__in=layers_with_mapped_data(MapLayer.objects.filter(is_active=True)).values("id"))
                .values_list("id", flat=True)
            )
            qs = MapLayer.objects.filter(Q(id__in=qs.values("id")) | Q(id__in=empty_ids)).distinct()

        layers = list(qs.order_by("name"))
        if not layers:
            self.stdout.write(self.style.SUCCESS("No placeholder layers matched."))
            return

        self.stdout.write(f"Matched {len(layers)} layer(s):")
        for layer in layers:
            active_features = MapFeature.objects.filter(layer=layer, is_active=True).count()
            self.stdout.write(
                f"  - [{layer.id}] {layer.name} ({layer.slug}, {layer.layer_type}) "
                f"active={layer.is_active} features={active_features}"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no changes made."))
            return

        layer_ids = [layer.id for layer in layers]
        feature_qs = MapFeature.objects.filter(layer_id__in=layer_ids)

        if hard_delete:
            deleted_features, _ = feature_qs.delete()
            deleted_layers, _ = MapLayer.objects.filter(id__in=layer_ids).delete()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {deleted_layers} layer(s) and {deleted_features} related row(s)."
                )
            )
            return

        feature_qs.filter(is_active=True).update(is_active=False)
        MapLayer.objects.filter(id__in=layer_ids, is_active=True).update(is_active=False)
        self.stdout.write(
            self.style.SUCCESS(f"Deactivated {len(layers)} placeholder layer(s) and their active features.")
        )
