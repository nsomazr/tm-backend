from django.utils.text import slugify
from rest_framework import serializers

from apps.marketplace.geometry import (
    derive_listing_center_and_bbox,
    normalize_listing_geometry,
)
from apps.reports.geometry import clamp_report_buffer_km

from .documents import DocumentValidationError, validate_document_upload
from .models import ListingDocument, ListingInquiry, MarketplaceListing

LISTING_SLUG_MAX_LENGTH = 70


def unique_listing_slug(title: str, *, exclude_pk: int | None = None) -> str:
    base = slugify(title) or "listing"
    base = base[:LISTING_SLUG_MAX_LENGTH].rstrip("-") or "listing"
    slug = base
    counter = 1
    qs = MarketplaceListing.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base[: LISTING_SLUG_MAX_LENGTH - len(suffix)]}{suffix}"
        counter += 1
    return slug


def _normalize_commodity_labels(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        return [p for p in parts if p][:20]
    if isinstance(value, list):
        labels = []
        for item in value:
            text = str(item).strip()
            if text and text not in labels:
                labels.append(text[:80])
            if len(labels) >= 20:
                break
        return labels
    raise serializers.ValidationError("commodity_labels must be a list of strings.")


def _compose_commodity_labels(primary: str, others: list[str]) -> list[str]:
    labels: list[str] = []
    primary_text = (primary or "").strip()[:80]
    if primary_text:
        labels.append(primary_text)
    for item in others:
        text = str(item).strip()[:80]
        if not text:
            continue
        if any(existing.lower() == text.lower() for existing in labels):
            continue
        labels.append(text)
        if len(labels) >= 20:
            break
    return labels


def _sync_mineral_fields(validated_data: dict, *, instance=None) -> dict:
    """Keep primary_mineral / other_minerals / commodity_labels in sync."""
    has_primary = "primary_mineral" in validated_data
    has_others = "other_minerals" in validated_data
    has_labels = "commodity_labels" in validated_data

    if has_primary or has_others:
        primary = validated_data.get(
            "primary_mineral",
            getattr(instance, "primary_mineral", "") if instance else "",
        )
        others = validated_data.get(
            "other_minerals",
            getattr(instance, "other_minerals", []) if instance else [],
        )
        primary = (primary or "").strip()[:80]
        others = _normalize_commodity_labels(others)
        others = [item for item in others if item.lower() != primary.lower()]
        validated_data["primary_mineral"] = primary
        validated_data["other_minerals"] = others
        validated_data["commodity_labels"] = _compose_commodity_labels(primary, others)
        return validated_data

    if has_labels:
        labels = _normalize_commodity_labels(validated_data.get("commodity_labels"))
        validated_data["commodity_labels"] = labels
        validated_data["primary_mineral"] = labels[0] if labels else ""
        validated_data["other_minerals"] = labels[1:]
    return validated_data


class ListingDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ListingDocument
        fields = ("id", "title", "file", "file_url", "is_public", "created_at")
        read_only_fields = ("id", "file_url", "created_at")
        extra_kwargs = {"file": {"write_only": True}}

    def get_file_url(self, obj: ListingDocument) -> str | None:
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def validate_file(self, value):
        try:
            validate_document_upload(getattr(value, "name", ""), getattr(value, "size", 0) or 0)
        except DocumentValidationError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value

    def validate_is_public(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)


class PublicListingDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ListingDocument
        fields = ("id", "title", "file_url", "created_at")

    def get_file_url(self, obj: ListingDocument) -> str | None:
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        if request:
            return request.build_absolute_uri(url)
        return url


class PublicListingListSerializer(serializers.ModelSerializer):
    commodity_labels = serializers.ListField(child=serializers.CharField(), read_only=True)
    other_minerals = serializers.ListField(child=serializers.CharField(), read_only=True)
    geometry_type = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceListing
        fields = (
            "id",
            "slug",
            "title",
            "summary",
            "commodity_labels",
            "primary_mineral",
            "other_minerals",
            "center_lat",
            "center_lng",
            "geometry_type",
            "buffer_km",
            "updated_at",
        )

    def get_geometry_type(self, obj: MarketplaceListing) -> str | None:
        geom = obj.geometry or {}
        return geom.get("type")


class PublicListingDetailSerializer(serializers.ModelSerializer):
    commodity_labels = serializers.ListField(child=serializers.CharField(), read_only=True)
    other_minerals = serializers.ListField(child=serializers.CharField(), read_only=True)
    documents = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    contact_email = serializers.SerializerMethodField()
    contact_phone = serializers.SerializerMethodField()
    geometry_type = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceListing
        fields = (
            "id",
            "slug",
            "title",
            "summary",
            "description",
            "geometry",
            "geometry_type",
            "buffer_km",
            "center_lat",
            "center_lng",
            "bounding_box",
            "commodity_labels",
            "primary_mineral",
            "other_minerals",
            "show_contact_public",
            "allow_inquiries",
            "contact_name",
            "contact_email",
            "contact_phone",
            "documents",
            "updated_at",
        )

    def get_geometry_type(self, obj: MarketplaceListing) -> str | None:
        return (obj.geometry or {}).get("type")

    def get_documents(self, obj: MarketplaceListing):
        docs = [d for d in obj.documents.all() if d.is_public]
        return PublicListingDocumentSerializer(docs, many=True, context=self.context).data

    def get_contact_name(self, obj: MarketplaceListing) -> str:
        return obj.contact_name if obj.show_contact_public else ""

    def get_contact_email(self, obj: MarketplaceListing) -> str:
        return obj.contact_email if obj.show_contact_public else ""

    def get_contact_phone(self, obj: MarketplaceListing) -> str:
        return obj.contact_phone if obj.show_contact_public else ""


class OwnerListingSerializer(serializers.ModelSerializer):
    documents = ListingDocumentSerializer(many=True, read_only=True)
    commodity_labels = serializers.JSONField(required=False)
    other_minerals = serializers.JSONField(required=False)
    inquiry_unread_count = serializers.SerializerMethodField()
    inquiry_count = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceListing
        fields = (
            "id",
            "slug",
            "title",
            "summary",
            "description",
            "geometry",
            "buffer_km",
            "center_lat",
            "center_lng",
            "bounding_box",
            "commodity_labels",
            "primary_mineral",
            "other_minerals",
            "status",
            "show_on_map",
            "contact_name",
            "contact_email",
            "contact_phone",
            "show_contact_public",
            "allow_inquiries",
            "country",
            "documents",
            "inquiry_unread_count",
            "inquiry_count",
            "view_count",
            "map_click_count",
            "document_download_count",
            "terra_summary_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "center_lat",
            "center_lng",
            "bounding_box",
            "documents",
            "inquiry_unread_count",
            "inquiry_count",
            "view_count",
            "map_click_count",
            "document_download_count",
            "terra_summary_count",
            "created_at",
            "updated_at",
        )

    def get_inquiry_unread_count(self, obj: MarketplaceListing) -> int:
        return getattr(obj, "inquiry_unread_count", None) or obj.inquiries.filter(is_read=False).count()

    def get_inquiry_count(self, obj: MarketplaceListing) -> int:
        return getattr(obj, "inquiry_count", None) or obj.inquiries.count()

    def validate_title(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters.")
        return text

    def validate_commodity_labels(self, value):
        return _normalize_commodity_labels(value)

    def validate_other_minerals(self, value):
        return _normalize_commodity_labels(value)

    def validate_primary_mineral(self, value):
        return (value or "").strip()[:80]

    def validate_geometry(self, value):
        if value in (None, "", {}, []):
            return {}
        try:
            return normalize_listing_geometry(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_buffer_km(self, value):
        if value in (None, "", 0):
            return None
        clamped = clamp_report_buffer_km(value)
        if clamped is None and value not in (None, "", 0):
            raise serializers.ValidationError("buffer_km must be between 1 and 20.")
        return clamped

    def validate_status(self, value: str) -> str:
        if value not in MarketplaceListing.Status.values:
            raise serializers.ValidationError("Invalid status.")
        return value

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        status = attrs.get("status", getattr(instance, "status", MarketplaceListing.Status.DRAFT))
        geometry = attrs.get("geometry", getattr(instance, "geometry", {}) if instance else {})
        if status == MarketplaceListing.Status.PUBLISHED and not geometry:
            raise serializers.ValidationError(
                {"geometry": "Add a point or polygon area before publishing."}
            )
        return attrs

    def _apply_derived_fields(self, validated_data: dict, *, instance: MarketplaceListing | None = None):
        geometry = validated_data.get("geometry")
        if geometry is None and instance is not None:
            geometry = instance.geometry or {}
        buffer_km = validated_data.get("buffer_km", getattr(instance, "buffer_km", None) if instance else None)
        if "geometry" in validated_data or "buffer_km" in validated_data or instance is None:
            lat, lng, bbox = derive_listing_center_and_bbox(geometry or {}, buffer_km)
            validated_data["center_lat"] = lat
            validated_data["center_lng"] = lng
            validated_data["bounding_box"] = bbox or {}
        return validated_data

    def create(self, validated_data):
        title = validated_data["title"]
        validated_data["slug"] = unique_listing_slug(title)
        validated_data = _sync_mineral_fields(validated_data)
        validated_data = self._apply_derived_fields(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "title" in validated_data and validated_data["title"] != instance.title:
            validated_data["slug"] = unique_listing_slug(
                validated_data["title"], exclude_pk=instance.pk
            )
        validated_data = _sync_mineral_fields(validated_data, instance=instance)
        validated_data = self._apply_derived_fields(validated_data, instance=instance)
        return super().update(instance, validated_data)


class ListingInquiryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingInquiry
        fields = ("message", "contact_email")

    def validate_message(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 10:
            raise serializers.ValidationError("Message must be at least 10 characters.")
        if len(text) > 4000:
            raise serializers.ValidationError("Message is too long.")
        return text


class ListingInquirySerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(source="listing.title", read_only=True)
    listing_slug = serializers.CharField(source="listing.slug", read_only=True)
    from_username = serializers.CharField(source="from_user.username", read_only=True)
    conversation_id = serializers.SerializerMethodField()

    class Meta:
        model = ListingInquiry
        fields = (
            "id",
            "listing",
            "listing_title",
            "listing_slug",
            "from_user",
            "from_username",
            "message",
            "contact_email",
            "is_read",
            "created_at",
            "conversation_id",
        )
        read_only_fields = fields

    def get_conversation_id(self, obj: ListingInquiry) -> int | None:
        from .models import ListingConversation

        conversation = ListingConversation.objects.filter(
            listing_id=obj.listing_id,
            buyer_id=obj.from_user_id,
        ).only("id").first()
        return conversation.id if conversation else None
