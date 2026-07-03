import json

from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .models import LayerUpload, LayerVersion, MapFeature, MapLayer


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
            "created_at",
            "updated_at",
        )
        read_only_fields = ("current_version", "created_at", "updated_at", "slug")

    def get_feature_count(self, obj):
        return obj.features.filter(is_active=True).count()

    def get_mineral_name(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return localized_name(obj.mineral, locale) if obj.mineral_id else ""


class MapLayerDetailSerializer(MapLayerSerializer):
    features = MapFeatureSerializer(many=True, read_only=True)

    class Meta(MapLayerSerializer.Meta):
        fields = MapLayerSerializer.Meta.fields + ("features",)


class LayerVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayerVersion
        fields = (
            "id",
            "layer",
            "version_number",
            "changelog",
            "uploaded_by",
            "feature_count",
            "created_at",
        )
        read_only_fields = ("version_number", "feature_count", "created_at")


class LayerUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LayerUpload
        fields = (
            "id",
            "layer",
            "file",
            "file_type",
            "status",
            "error_message",
            "created_at",
        )
        read_only_fields = ("status", "error_message", "created_at")


class LayerReorderSerializer(serializers.Serializer):
    layer_ids = serializers.ListField(child=serializers.IntegerField())
