from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .access import user_has_report_detail_access
from .models import Report, ReportSummary


class ReportSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportSummary
        fields = ("summary", "key_findings", "generated_at", "model_used")


class ReportSerializer(serializers.ModelSerializer):
    mineral_name = serializers.SerializerMethodField()
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)
    ai_summary = serializers.SerializerMethodField()
    is_purchased = serializers.SerializerMethodField()
    has_full_access = serializers.SerializerMethodField()
    key_findings_count = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = (
            "id",
            "title",
            "slug",
            "mineral",
            "mineral_name",
            "region",
            "region_name",
            "description",
            "bounding_box",
            "preview_image",
            "price",
            "currency",
            "is_active",
            "ai_summary",
            "has_full_access",
            "key_findings_count",
            "is_purchased",
            "created_at",
        )
        read_only_fields = ("created_at",)

    def _has_detail(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        return user_has_report_detail_access(user, obj)

    def get_has_full_access(self, obj):
        return self._has_detail(obj)

    def get_key_findings_count(self, obj):
        if not hasattr(obj, "ai_summary") or obj.ai_summary is None:
            return 0
        return len(obj.ai_summary.key_findings or [])

    def get_ai_summary(self, obj):
        if not hasattr(obj, "ai_summary") or obj.ai_summary is None:
            return None
        summary_obj = obj.ai_summary
        if self._has_detail(obj):
            return ReportSummarySerializer(summary_obj).data

        summary = summary_obj.summary or ""
        if len(summary) > 280:
            teaser = summary[:280].rsplit(" ", 1)[0] + "…"
        else:
            teaser = summary
        return {
            "summary": teaser,
            "generated_at": summary_obj.generated_at,
            "is_preview": True,
        }

    def get_is_purchased(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.purchases.filter(user=request.user).exists()

    def get_mineral_name(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return localized_name(obj.mineral, locale) if obj.mineral_id else ""


class ReportAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = (
            "id",
            "title",
            "slug",
            "mineral",
            "region",
            "description",
            "bounding_box",
            "pdf_file",
            "preview_image",
            "price",
            "currency",
            "is_active",
            "created_at",
        )
        read_only_fields = ("slug", "created_at")

    def create(self, validated_data):
        from django.utils.text import slugify
        title = validated_data["title"]
        base_slug = slugify(title)
        slug = base_slug
        counter = 1
        while Report.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        validated_data["slug"] = slug
        return super().create(validated_data)
