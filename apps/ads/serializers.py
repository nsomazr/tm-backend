import json

from django.utils.text import slugify
from rest_framework import serializers

from config.media import public_ad_image_url

from .models import Ad, AdAudience, AdPlacement


def _coerce_json_form_value(data):
    """Multipart uploads sometimes wrap JSON strings in single-item lists."""
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], str):
        candidate = data[0].strip()
        if candidate.startswith("[") or candidate.startswith("{"):
            return candidate
    return data


def _form_data_to_dict(data):
    """Normalize QueryDict / multipart bodies to a plain dict for coercion."""
    if hasattr(data, "getlist"):
        result = {}
        for key in data.keys():
            values = data.getlist(key)
            if len(values) == 1:
                result[key] = _coerce_json_form_value(values[0])
            else:
                result[key] = [_coerce_json_form_value(value) for value in values]
        return result
    if hasattr(data, "items"):
        return {key: _coerce_json_form_value(value) for key, value in data.items()}
    return dict(data)


class AdPublicSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = (
            "id",
            "title",
            "company_name",
            "headline",
            "body_text",
            "image_url",
            "cta_label",
            "link_url",
            "open_in_new_tab",
        )

    def get_image_url(self, obj):
        return public_ad_image_url(self.context.get("request"), obj)


class AdAdminSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    click_through_rate = serializers.FloatField(read_only=True)
    is_live = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    placement_labels = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = (
            "id",
            "title",
            "slug",
            "company_name",
            "headline",
            "body_text",
            "image",
            "image_url",
            "cta_label",
            "link_url",
            "open_in_new_tab",
            "placements",
            "placement_labels",
            "priority",
            "is_active",
            "is_hidden",
            "audience",
            "country_codes",
            "starts_at",
            "ends_at",
            "impression_count",
            "click_count",
            "click_through_rate",
            "is_live",
            "status_label",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "slug",
            "impression_count",
            "click_count",
            "click_through_rate",
            "is_live",
            "status_label",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        )

    def get_image_url(self, obj):
        return public_ad_image_url(self.context.get("request"), obj)

    def get_is_live(self, obj):
        return obj.is_live()

    def get_status_label(self, obj):
        from django.utils import timezone

        now = timezone.now()
        if obj.is_hidden:
            return "hidden"
        if not obj.is_active:
            return "inactive"
        if obj.ends_at and obj.ends_at < now:
            return "expired"
        if obj.starts_at and obj.starts_at > now:
            return "scheduled"
        if obj.is_live(now=now):
            return "live"
        return "inactive"

    def to_internal_value(self, data):
        mutable = _form_data_to_dict(data)
        for key in ("placements", "country_codes"):
            raw = mutable.get(key)
            if isinstance(raw, str) and raw.strip():
                try:
                    mutable[key] = json.loads(raw)
                except json.JSONDecodeError:
                    if key == "country_codes":
                        mutable[key] = [part.strip().upper() for part in raw.split(",") if part.strip()]
        for key in ("is_active", "is_hidden", "open_in_new_tab"):
            raw = mutable.get(key)
            if isinstance(raw, str):
                mutable[key] = raw.lower() in ("true", "1", "yes", "on")
        if "priority" in mutable and isinstance(mutable.get("priority"), str):
            try:
                mutable["priority"] = int(mutable["priority"])
            except ValueError:
                pass
        return super().to_internal_value(mutable)

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return ""
        return obj.created_by.get_full_name() or obj.created_by.username

    def get_placement_labels(self, obj):
        labels = dict(AdPlacement.choices)
        return [labels.get(code, code) for code in (obj.placements or [])]

    def validate_placements(self, value):
        if self.partial and "placements" not in getattr(self, "initial_data", {}):
            return value
        if not value:
            raise serializers.ValidationError("Select at least one placement.")
        invalid = [code for code in value if code not in AdPlacement.values]
        if invalid:
            raise serializers.ValidationError(f"Unknown placements: {', '.join(invalid)}")
        return value

    def validate_audience(self, value):
        if value not in AdAudience.values:
            raise serializers.ValidationError("Invalid audience.")
        return value

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and ends_at < starts_at:
            raise serializers.ValidationError({"ends_at": "End time must be after start time."})
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        title = validated_data.get("title", "")
        base_slug = slugify(title) or "ad"
        slug = base_slug
        counter = 1
        while Ad.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        validated_data["slug"] = slug
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class AdTrackSerializer(serializers.Serializer):
    ad_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["impression", "click"])
    placement = serializers.ChoiceField(choices=AdPlacement.choices)
