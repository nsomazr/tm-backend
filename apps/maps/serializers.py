import json

from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .models import LayerUpload, LayerVersion, MapFeature, MapLayer


def _user_display_name(user) -> str | None:
    if not user:
        return None
    return user.get_full_name() or user.username or None


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
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate_geometry(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Geometry must be a GeoJSON object.")
        if "type" not in value:
            raise serializers.ValidationError("Geometry must have a type field.")
        return value


class MapLayerSerializer(serializers.ModelSerializer):
    mineral_name = serializers.SerializerMethodField()
    mineral_slug = serializers.CharField(source="mineral.slug", read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)
    feature_count = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    last_uploaded_by_name = serializers.SerializerMethodField()
    last_uploaded_at = serializers.SerializerMethodField()

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
            "current_version",
            "feature_count",
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
        )

    def get_feature_count(self, obj):
        return obj.features.filter(is_active=True).count()

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


class MapLayerDetailSerializer(MapLayerSerializer):
    features = MapFeatureSerializer(many=True, read_only=True)

    class Meta(MapLayerSerializer.Meta):
        fields = MapLayerSerializer.Meta.fields + ("features",)


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
