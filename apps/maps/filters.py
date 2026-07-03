import django_filters

from .models import MapLayer


class MapLayerFilter(django_filters.FilterSet):
    mineral_slug = django_filters.CharFilter(field_name="mineral__slug")

    class Meta:
        model = MapLayer
        fields = ["mineral", "region", "layer_type", "is_preview", "is_active", "mineral_slug"]
