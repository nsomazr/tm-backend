import json

from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .access import user_can_download_report, user_has_report_detail_access
from .models import Report, ReportSummary


def _parse_key_findings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        return [
            line.strip().lstrip("-•").strip()
            for line in text.splitlines()
            if line.strip()
        ]
    return []


class FlexibleKeyFindingsField(serializers.Field):
    def to_internal_value(self, data):
        return _parse_key_findings(data)

    def to_representation(self, value):
        return value


def _preview_teaser(summary: str, *, mode: str = "list") -> str:
    if not summary:
        return ""
    if mode == "detail":
        if len(summary) <= 320:
            return summary
        cut = max(320, min(int(len(summary) * 0.55), 960))
        if cut >= len(summary):
            return summary
        return summary[:cut].rsplit(" ", 1)[0] + "…"
    if len(summary) > 280:
        return summary[:280].rsplit(" ", 1)[0] + "…"
    return summary


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
    can_download = serializers.SerializerMethodField()
    download_source = serializers.SerializerMethodField()

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
            "can_download",
            "download_source",
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
        preview_mode = self.context.get("preview_mode", "list")
        teaser = _preview_teaser(summary, mode=preview_mode)
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

    def get_can_download(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        allowed, _ = user_can_download_report(request.user, obj)
        return allowed

    def get_download_source(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        _, source = user_can_download_report(request.user, obj)
        return source

    def get_mineral_name(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return localized_name(obj.mineral, locale) if obj.mineral_id else ""


class ReportAdminSerializer(serializers.ModelSerializer):
    mineral_name = serializers.CharField(source="mineral.name", read_only=True)
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)
    has_pdf = serializers.SerializerMethodField()
    summary_preview = serializers.SerializerMethodField()
    ai_summary = ReportSummarySerializer(read_only=True)
    executive_summary = serializers.CharField(required=False, allow_blank=True, write_only=True)
    key_findings = FlexibleKeyFindingsField(required=False, write_only=True)

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
            "pdf_file",
            "has_pdf",
            "preview_image",
            "price",
            "currency",
            "is_active",
            "summary_preview",
            "ai_summary",
            "executive_summary",
            "key_findings",
            "created_at",
        )
        read_only_fields = ("slug", "created_at", "mineral_name", "region_name", "has_pdf", "summary_preview", "ai_summary")

    def get_has_pdf(self, obj):
        return bool(obj.pdf_file)

    def get_summary_preview(self, obj):
        if hasattr(obj, "ai_summary") and obj.ai_summary:
            text = obj.ai_summary.summary or ""
            return text[:200] + ("…" if len(text) > 200 else "")
        return ""

    def validate_pdf_file(self, value):
        if not value:
            return value

        name = (value.name or "").lower()
        if name.endswith(".pdf"):
            return value

        if name.endswith(".docx"):
            from .document_conversion import docx_upload_to_pdf_file

            try:
                return docx_upload_to_pdf_file(value)
            except Exception as exc:
                raise serializers.ValidationError(
                    f"Could not convert Word document to PDF: {exc}"
                ) from exc

        raise serializers.ValidationError("Upload a PDF or Word document (.docx).")

    def _save_manual_summary(self, report, executive_summary: str, key_findings: list[str] | None):
        summary_text = executive_summary.strip()
        if not summary_text and not key_findings:
            return False

        defaults = {
            "summary": summary_text,
            "model_used": "manual",
        }
        if key_findings is not None:
            defaults["key_findings"] = key_findings

        ReportSummary.objects.update_or_create(report=report, defaults=defaults)
        self.context["manual_summary_saved"] = True
        return True

    def create(self, validated_data):
        from django.utils.text import slugify

        executive_summary = validated_data.pop("executive_summary", "")
        key_findings = validated_data.pop("key_findings", None)

        title = validated_data["title"]
        base_slug = slugify(title)
        slug = base_slug
        counter = 1
        while Report.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        validated_data["slug"] = slug

        report = super().create(validated_data)
        self._save_manual_summary(report, executive_summary, key_findings)
        return report

    def update(self, instance, validated_data):
        executive_summary = validated_data.pop("executive_summary", None)
        key_findings = validated_data.pop("key_findings", None)

        report = super().update(instance, validated_data)

        if executive_summary is not None:
            self._save_manual_summary(report, executive_summary, key_findings)
        elif key_findings is not None:
            report.refresh_from_db()
            existing = ""
            if hasattr(report, "ai_summary") and report.ai_summary:
                existing = report.ai_summary.summary or ""
            self._save_manual_summary(report, existing, key_findings)

        return report
