from rest_framework import serializers

from .models import AdminBoundary, BoundaryGeologyDocument, Country, GeoReference, Region


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = (
            "id",
            "code",
            "name",
            "name_sw",
            "center_lat",
            "center_lng",
            "default_zoom",
            "bounds",
            "coordinate_system",
            "is_active",
        )


class RegionSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(source="country.name", read_only=True)

    class Meta:
        model = Region
        fields = ("id", "country", "country_name", "name", "name_sw", "bounds", "is_active")


class BoundaryGeologyDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoundaryGeologyDocument
        fields = ("id", "title", "scope", "file", "extracted_text", "created_at")
        read_only_fields = ("id", "extracted_text", "created_at")


class AdminBoundaryListItemSerializer(serializers.ModelSerializer):
    has_geology = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = AdminBoundary
        fields = (
            "id",
            "level",
            "name",
            "name_sw",
            "code",
            "has_geology",
            "document_count",
        )

    def get_has_geology(self, obj: AdminBoundary) -> bool:
        if (obj.geological_summary or "").strip() or (obj.geological_summary_sw or "").strip():
            return True
        metadata = obj.geological_metadata if isinstance(obj.geological_metadata, dict) else {}
        if metadata:
            return True
        count = getattr(obj, "geology_document_count", None)
        if count is not None:
            return count > 0
        return obj.geology_documents.exists()

    def get_document_count(self, obj: AdminBoundary) -> int:
        return getattr(obj, "geology_document_count", 0) or obj.geology_documents.count()


class AdminBoundaryGeologyUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminBoundary
        fields = ("geological_summary", "geological_summary_sw", "geological_metadata")


class AdminBoundaryGeologySerializer(serializers.ModelSerializer):
    documents = BoundaryGeologyDocumentSerializer(source="geology_documents", many=True, read_only=True)
    level_label = serializers.SerializerMethodField()

    class Meta:
        model = AdminBoundary
        fields = (
            "id",
            "level",
            "level_label",
            "name",
            "name_sw",
            "code",
            "geological_summary",
            "geological_summary_sw",
            "geological_metadata",
            "documents",
            "updated_at",
        )
        read_only_fields = ("id", "level", "name", "name_sw", "code", "updated_at")

    def get_level_label(self, obj: AdminBoundary) -> str:
        return AdminBoundary.Level(obj.level).label


class GeoReferenceSerializer(serializers.ModelSerializer):
    country_code = serializers.CharField(source="country.code", read_only=True, allow_null=True)
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = GeoReference
        fields = (
            "id",
            "name",
            "slug",
            "country",
            "country_code",
            "source_filename",
            "feature_count",
            "bounds",
            "is_active",
            "uploaded_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_uploaded_by_name(self, obj: GeoReference) -> str:
        if obj.uploaded_by_id and obj.uploaded_by:
            return obj.uploaded_by.get_username()
        return ""
