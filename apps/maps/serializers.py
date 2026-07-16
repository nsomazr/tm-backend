import json

from django.core.cache import cache
from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name
from apps.minerals.models import Mineral

from apps.minerals.color_utils import enrich_layer_style

from .geometry_utils import geometry_area_km2
from .models import (
    BUFFER_KM_MAX,
    BUFFER_KM_MIN,
    HEATMAP_WEIGHT_MAX,
    HEATMAP_WEIGHT_MIN,
    LayerUpload,
    LayerVersion,
    MapFeature,
    MapLayer,
    SavedExploration,
)


def _user_display_name(user) -> str | None:
    if not user:
        return None
    return user.get_full_name() or user.username or None


_LAYER_GEOMETRY_TYPES = {
    "point": ("Point", "MultiPoint"),
    "line": ("LineString", "MultiLineString"),
    "polygon": ("Polygon", "MultiPolygon"),
}


def _centroid_from_geometry(geometry: dict) -> tuple[float | None, float | None]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None, None

    points: list[list[float]] = []
    if gtype == "Point":
        points = [coords]
    elif gtype == "MultiPoint":
        points = coords
    elif gtype == "LineString":
        points = coords
    elif gtype == "MultiLineString":
        for part in coords:
            points.extend(part)
    elif gtype == "Polygon":
        ring = coords[0]
        if len(ring) > 1 and ring[0] == ring[-1]:
            points = ring[:-1]
        else:
            points = ring
    elif gtype == "MultiPolygon":
        for poly in coords:
            ring = poly[0]
            if len(ring) > 1 and ring[0] == ring[-1]:
                points.extend(ring[:-1])
            else:
                points.extend(ring)

    if not points:
        return None, None
    lng = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lng


class MapFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapFeature
        fields = (
            "id",
            "layer",
            "geometry",
            "properties",
            "latitude",
            "longitude",
            "label",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at", "created_by")

    def validate_geometry(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Geometry must be a GeoJSON object.")
        if "type" not in value:
            raise serializers.ValidationError("Geometry must have a type field.")
        return value

    def validate(self, attrs):
        layer = attrs.get("layer") or getattr(self.instance, "layer", None)
        geometry = attrs.get("geometry") or getattr(self.instance, "geometry", None)
        if layer and geometry:
            allowed = _LAYER_GEOMETRY_TYPES.get(layer.layer_type, ())
            gtype = geometry.get("type")
            if gtype not in allowed:
                raise serializers.ValidationError(
                    {
                        "geometry": (
                            f"Layer type “{layer.layer_type}” expects "
                            f"{', '.join(allowed)} geometry, not {gtype}."
                        )
                    }
                )
        return attrs

    def create(self, validated_data):
        geometry = validated_data.get("geometry")
        if geometry:
            lat, lng = _centroid_from_geometry(geometry)
            if lat is not None and lng is not None:
                validated_data.setdefault("latitude", lat)
                validated_data.setdefault("longitude", lng)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        geometry = validated_data.get("geometry", instance.geometry)
        if geometry:
            lat, lng = _centroid_from_geometry(geometry)
            if lat is not None and lng is not None:
                validated_data.setdefault("latitude", lat)
                validated_data.setdefault("longitude", lng)
        return super().update(instance, validated_data)


def _cached_layer_area_km2(layer: MapLayer) -> float:
    """Total polygon coverage (km²) for stack ordering; 0 for non-polygon layers."""
    if layer.layer_type != MapLayer.LayerType.POLYGON:
        return 0.0
    cache_key = f"map_layer_area_km2:v1:{layer.pk}:{layer.current_version}"
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            return float(cached)
        except (TypeError, ValueError):
            pass
    total = 0.0
    for geometry in (
        MapFeature.objects.filter(layer_id=layer.pk, is_active=True)
        .values_list("geometry", flat=True)
        .iterator(chunk_size=256)
    ):
        total += geometry_area_km2(geometry)
    total = round(max(0.0, total), 2)
    cache.set(cache_key, total, 60 * 60)
    return total


class MapLayerSerializer(serializers.ModelSerializer):
    mineral_name = serializers.SerializerMethodField()
    mineral_slug = serializers.CharField(source="mineral.slug", read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)
    feature_count = serializers.SerializerMethodField()
    area_km2 = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    last_uploaded_by_name = serializers.SerializerMethodField()
    last_uploaded_at = serializers.SerializerMethodField()
    associated_catalog_slugs = serializers.SerializerMethodField()
    mineral = serializers.PrimaryKeyRelatedField(
        queryset=Mineral.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = MapLayer
        fields = (
            "id",
            "name",
            "name_sw",
            "slug",
            "layer_type",
            "mineral",
            "mineral_name",
            "mineral_slug",
            "region",
            "region_name",
            "z_index",
            "is_preview",
            "is_active",
            "style",
            "description",
            "buffer_km",
            "heatmap_weight",
            "associated_catalog_slugs",
            "current_version",
            "feature_count",
            "area_km2",
            "created_by",
            "created_by_name",
            "last_uploaded_by_name",
            "last_uploaded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "current_version",
            "created_at",
            "updated_at",
            "slug",
            "created_by",
            "created_by_name",
            "last_uploaded_by_name",
            "last_uploaded_at",
            "associated_catalog_slugs",
        )

    def get_feature_count(self, obj):
        for attr in ("annotated_feature_count", "active_feature_count"):
            value = getattr(obj, attr, None)
            if value is not None:
                return value
        return obj.features.filter(is_active=True).count()

    def get_area_km2(self, obj):
        return _cached_layer_area_km2(obj)

    def get_mineral_name(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return localized_name(obj.mineral, locale) if obj.mineral_id else ""

    def get_created_by_name(self, obj):
        return _user_display_name(getattr(obj, "created_by", None))

    def _latest_version(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "versions" in obj._prefetched_objects_cache:
            versions = obj._prefetched_objects_cache["versions"]
            return versions[0] if versions else None
        return obj.versions.select_related("uploaded_by").order_by("-version_number").first()

    def get_last_uploaded_by_name(self, obj):
        version = self._latest_version(obj)
        return _user_display_name(version.uploaded_by) if version else None

    def get_last_uploaded_at(self, obj):
        version = self._latest_version(obj)
        return version.created_at if version else None

    def get_associated_catalog_slugs(self, obj):
        # Prefetch via associated_minerals when available.
        minerals = getattr(obj, "associated_minerals", None)
        if minerals is None:
            return []
        if hasattr(obj, "_prefetched_objects_cache") and "associated_minerals" in obj._prefetched_objects_cache:
            return [m.slug for m in minerals.all()]
        return list(minerals.filter(is_active=True).values_list("slug", flat=True))

    def validate_style(self, value):
        layer_type = (
            self.initial_data.get("layer_type")
            if hasattr(self, "initial_data")
            else None
        )
        if not layer_type and self.instance:
            layer_type = self.instance.layer_type
        layer_name = ""
        preferred_hex = None
        used_colors: list[str] = []
        suggest_if_empty = not self.instance
        if hasattr(self, "initial_data"):
            layer_name = str(self.initial_data.get("name") or "")
            mineral_id = self.initial_data.get("mineral")
            if mineral_id:
                from apps.minerals.models import Mineral

                mineral = Mineral.objects.filter(pk=mineral_id).only("color").first()
                if mineral and mineral.color:
                    preferred_hex = mineral.color
        if suggest_if_empty:
            from apps.maps.models import MapLayer

            for style in MapLayer.objects.filter(is_active=True).values_list("style", flat=True):
                if not isinstance(style, dict):
                    continue
                fill = style.get("fill") or style.get("stroke")
                if isinstance(fill, str) and fill.strip():
                    used_colors.append(fill)
        return enrich_layer_style(
            value or {},
            layer_type or "polygon",
            layer_name=layer_name,
            preferred_hex=preferred_hex,
            used_colors=used_colors,
            suggest_if_empty=suggest_if_empty,
        )

    def validate_buffer_km(self, value):
        if value is None:
            return value
        if value < BUFFER_KM_MIN or value > BUFFER_KM_MAX:
            raise serializers.ValidationError(
                f"Buffer zone must be between {BUFFER_KM_MIN} and {BUFFER_KM_MAX} km."
            )
        return value

    def validate_heatmap_weight(self, value):
        if value is None:
            return value
        if value < HEATMAP_WEIGHT_MIN or value > HEATMAP_WEIGHT_MAX:
            raise serializers.ValidationError(
                f"Heatmap weight must be between {HEATMAP_WEIGHT_MIN} and {HEATMAP_WEIGHT_MAX}."
            )
        return value

    def create(self, validated_data):
        style = validated_data.get("style") or {}
        if not style.get("fill") and not style.get("stroke"):
            from apps.maps.models import MapLayer
            from apps.minerals.color_utils import enrich_layer_style

            used_colors = []
            for existing in MapLayer.objects.filter(is_active=True).values_list("style", flat=True):
                if isinstance(existing, dict):
                    fill = existing.get("fill") or existing.get("stroke")
                    if isinstance(fill, str) and fill.strip():
                        used_colors.append(fill)
            mineral = validated_data.get("mineral")
            preferred = getattr(mineral, "color", None) if mineral else None
            validated_data["style"] = enrich_layer_style(
                {},
                validated_data.get("layer_type") or "polygon",
                layer_name=validated_data.get("name") or "",
                preferred_hex=preferred,
                used_colors=used_colors,
                suggest_if_empty=True,
            )
        layer = super().create(validated_data)
        self._sync_mineral_color(layer)
        return layer

    def update(self, instance, validated_data):
        layer = super().update(instance, validated_data)
        if "style" in validated_data:
            self._sync_mineral_color(layer)
        return layer

    def _sync_mineral_color(self, layer):
        from apps.maps.layer_defaults import sync_mineral_color_from_layer

        if layer.mineral_id and layer.style:
            sync_mineral_color_from_layer(layer.mineral, layer.style, layer.layer_type)


class MapLayerDetailSerializer(MapLayerSerializer):
    features = MapFeatureSerializer(many=True, read_only=True)

    class Meta(MapLayerSerializer.Meta):
        fields = MapLayerSerializer.Meta.fields + ("features",)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Match the geojson endpoint: anonymous / free users get precision-reduced
        # geometry and no detailed feature properties. Paid users see full data.
        from .access import coarsen_geometry, preview_coord_decimals, user_has_map_detail_access

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user_has_map_detail_access(user):
            return data

        decimals = preview_coord_decimals()
        for feature in data.get("features", []):
            if feature.get("geometry"):
                feature["geometry"] = coarsen_geometry(feature["geometry"], decimals)
            feature["properties"] = {}
            if feature.get("latitude") is not None:
                feature["latitude"] = round(float(feature["latitude"]), decimals)
            if feature.get("longitude") is not None:
                feature["longitude"] = round(float(feature["longitude"]), decimals)
        return data


class LayerVersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    layer_name = serializers.CharField(source="layer.name", read_only=True)
    layer_slug = serializers.CharField(source="layer.slug", read_only=True)
    mineral_name = serializers.CharField(source="layer.mineral.name", read_only=True)

    class Meta:
        model = LayerVersion
        fields = (
            "id",
            "layer",
            "layer_name",
            "layer_slug",
            "mineral_name",
            "version_number",
            "changelog",
            "uploaded_by",
            "uploaded_by_name",
            "feature_count",
            "created_at",
        )
        read_only_fields = ("version_number", "feature_count", "created_at")

    def get_uploaded_by_name(self, obj):
        return _user_display_name(obj.uploaded_by)


class LayerUploadSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    uploaded_by_role = serializers.CharField(source="uploaded_by.role", read_only=True, default=None)
    layer_name = serializers.CharField(source="layer.name", read_only=True)
    layer_slug = serializers.CharField(source="layer.slug", read_only=True)
    mineral_name = serializers.CharField(source="layer.mineral.name", read_only=True)
    filename = serializers.SerializerMethodField()

    class Meta:
        model = LayerUpload
        fields = (
            "id",
            "layer",
            "layer_name",
            "layer_slug",
            "mineral_name",
            "filename",
            "file_type",
            "import_mode",
            "status",
            "error_message",
            "uploaded_by",
            "uploaded_by_name",
            "uploaded_by_role",
            "created_at",
        )
        read_only_fields = ("status", "error_message", "created_at")

    def get_uploaded_by_name(self, obj):
        return _user_display_name(obj.uploaded_by)

    def get_filename(self, obj):
        if not obj.file:
            return ""
        return obj.file.name.rsplit("/", 1)[-1]


class LayerReorderSerializer(serializers.Serializer):
    layer_ids = serializers.ListField(child=serializers.IntegerField())


class SavedExplorationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedExploration
        fields = ("id", "name", "mode", "points", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")

    def validate_points(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("points must be a non-empty list of [lng, lat] pairs.")
        cleaned: list[list[float]] = []
        for pair in value:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(isinstance(n, (int, float)) for n in pair)
            ):
                raise serializers.ValidationError("Each point must be a [lng, lat] numeric pair.")
            lng, lat = float(pair[0]), float(pair[1])
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                raise serializers.ValidationError("Coordinates out of range.")
            cleaned.append([lng, lat])
        if len(cleaned) > 500:
            raise serializers.ValidationError("Too many points (max 500).")
        return cleaned

    def validate(self, attrs):
        mode = attrs.get("mode", getattr(self.instance, "mode", "point"))
        points = attrs.get("points", getattr(self.instance, "points", []))
        minimum = {"point": 1, "line": 2, "polygon": 3}.get(mode, 1)
        if len(points) < minimum:
            raise serializers.ValidationError(f"A {mode} needs at least {minimum} point(s).")
        return attrs
