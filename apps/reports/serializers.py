import json

from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .access import user_can_download_report, user_has_report_detail_access
from .models import Report, ReportSummary, UserExplorationReport
from .pdf_service import _html_to_report_text


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


class JSONListField(serializers.ListField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("Invalid JSON list.") from exc
        return super().to_internal_value(data)


class JSONDictField(serializers.JSONField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("Invalid JSON object.") from exc
        return super().to_internal_value(data)


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


class LinkedLayerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class LocationTagSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    level = serializers.IntegerField()
    level_label = serializers.CharField()


class ReportSerializer(serializers.ModelSerializer):
    mineral_name = serializers.SerializerMethodField()
    region_name = serializers.CharField(source="region.name", read_only=True, default=None)
    ai_summary = serializers.SerializerMethodField()
    is_purchased = serializers.SerializerMethodField()
    has_full_access = serializers.SerializerMethodField()
    key_findings_count = serializers.SerializerMethodField()
    can_download = serializers.SerializerMethodField()
    download_source = serializers.SerializerMethodField()
    has_pdf = serializers.SerializerMethodField()
    has_article = serializers.BooleanField(read_only=True)
    article_body = serializers.SerializerMethodField()
    linked_layers = serializers.SerializerMethodField()
    location_tags = serializers.SerializerMethodField()
    allowed_plan_ids = serializers.SerializerMethodField()

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
            "source_type",
            "access_type",
            "report_format",
            "bounding_box",
            "center_lat",
            "center_lng",
            "zoom",
            "preview_image",
            "price",
            "currency",
            "is_active",
            "has_pdf",
            "has_article",
            "article_body",
            "linked_layers",
            "location_tags",
            "allowed_plan_ids",
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

    def get_has_pdf(self, obj):
        return bool(obj.pdf_file)

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

    def get_article_body(self, obj):
        if not obj.has_article:
            return []
        if not self._has_detail(obj):
            return []
        return obj.article_body or []

    def get_linked_layers(self, obj):
        locale = get_request_locale(self.context.get("request"))
        rows = []
        for layer in obj.layers.all():
            rows.append(
                {
                    "id": layer.id,
                    "slug": layer.slug,
                    "name": localized_name(layer, locale),
                }
            )
        return rows

    def get_location_tags(self, obj):
        level_labels = {1: "region", 2: "district", 3: "ward", 4: "village"}
        return [
            {
                "id": boundary.id,
                "name": boundary.name,
                "level": boundary.level,
                "level_label": level_labels.get(boundary.level, "boundary"),
            }
            for boundary in obj.boundaries.all()[:20]
        ]

    def get_allowed_plan_ids(self, obj):
        return list(obj.allowed_plans.values_list("id", flat=True))

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
    layer_ids = JSONListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )
    boundary_ids = JSONListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )
    allowed_plan_ids = JSONListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
    )
    bounding_box = JSONDictField(required=False)
    linked_layers = serializers.SerializerMethodField()
    location_tags = serializers.SerializerMethodField()
    has_article = serializers.BooleanField(read_only=True)

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
            "source_type",
            "access_type",
            "report_format",
            "bounding_box",
            "center_lat",
            "center_lng",
            "zoom",
            "article_body",
            "pdf_file",
            "has_pdf",
            "has_article",
            "preview_image",
            "price",
            "currency",
            "is_active",
            "layer_ids",
            "boundary_ids",
            "allowed_plan_ids",
            "linked_layers",
            "location_tags",
            "summary_preview",
            "ai_summary",
            "executive_summary",
            "key_findings",
            "created_at",
        )
        read_only_fields = (
            "slug",
            "created_at",
            "mineral_name",
            "region_name",
            "has_pdf",
            "has_article",
            "summary_preview",
            "ai_summary",
            "linked_layers",
            "location_tags",
        )

    def get_has_pdf(self, obj):
        return bool(obj.pdf_file)

    def get_summary_preview(self, obj):
        if hasattr(obj, "ai_summary") and obj.ai_summary:
            text = _html_to_report_text(obj.ai_summary.summary or "")
            return text[:200] + ("…" if len(text) > 200 else "")
        return ""

    def get_linked_layers(self, obj):
        return [
            {"id": layer.id, "slug": layer.slug, "name": layer.name}
            for layer in obj.layers.all()
        ]

    def get_location_tags(self, obj):
        level_labels = {1: "region", 2: "district", 3: "ward", 4: "village"}
        return [
            {
                "id": boundary.id,
                "name": boundary.name,
                "level": boundary.level,
                "level_label": level_labels.get(boundary.level, "boundary"),
            }
            for boundary in obj.boundaries.all()
        ]

    def validate(self, attrs):
        report_format = attrs.get("report_format", getattr(self.instance, "report_format", None))
        access_type = attrs.get("access_type", getattr(self.instance, "access_type", None))
        pdf_file = attrs.get("pdf_file")
        source_type = attrs.get("source_type", getattr(self.instance, "source_type", None))

        is_upload = pdf_file or (
            self.instance
            and self.instance.source_type == Report.SourceType.UPLOADED
            and bool(self.instance.pdf_file)
        )
        if is_upload or source_type == Report.SourceType.UPLOADED:
            attrs["report_format"] = Report.ReportFormat.PDF
            attrs["source_type"] = Report.SourceType.UPLOADED
        elif source_type is None and not self.instance:
            attrs.setdefault("source_type", Report.SourceType.AI_GENERATED)

        if report_format == Report.ReportFormat.WEB_ARTICLE and is_upload:
            raise serializers.ValidationError(
                {"report_format": "Uploaded reports must use PDF format."}
            )

        plan_ids = attrs.get("allowed_plan_ids")
        if access_type == Report.AccessType.SUBSCRIBER_ONLY:
            existing = []
            if self.instance:
                existing = list(self.instance.allowed_plans.values_list("id", flat=True))
            if plan_ids is not None:
                if not plan_ids:
                    raise serializers.ValidationError(
                        {"allowed_plan_ids": "Select at least one subscription plan."}
                    )
            elif not existing:
                raise serializers.ValidationError(
                    {"allowed_plan_ids": "Select at least one subscription plan."}
                )

        return attrs

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

    def _save_m2m(self, report, layer_ids, boundary_ids, allowed_plan_ids):
        if layer_ids is not None:
            report.layers.set(layer_ids)
        if boundary_ids is not None:
            report.boundaries.set(boundary_ids)
        if allowed_plan_ids is not None:
            report.allowed_plans.set(allowed_plan_ids)

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
        layer_ids = validated_data.pop("layer_ids", None)
        boundary_ids = validated_data.pop("boundary_ids", None)
        allowed_plan_ids = validated_data.pop("allowed_plan_ids", None)

        title = validated_data["title"]
        base_slug = slugify(title)
        slug = base_slug
        counter = 1
        while Report.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        validated_data["slug"] = slug

        report = super().create(validated_data)
        self._save_m2m(report, layer_ids, boundary_ids, allowed_plan_ids)
        self._save_manual_summary(report, executive_summary, key_findings)
        return report

    def update(self, instance, validated_data):
        executive_summary = validated_data.pop("executive_summary", None)
        key_findings = validated_data.pop("key_findings", None)
        layer_ids = validated_data.pop("layer_ids", None)
        boundary_ids = validated_data.pop("boundary_ids", None)
        allowed_plan_ids = validated_data.pop("allowed_plan_ids", None)

        report = super().update(instance, validated_data)
        self._save_m2m(report, layer_ids, boundary_ids, allowed_plan_ids)

        if executive_summary is not None:
            self._save_manual_summary(report, executive_summary, key_findings)
        elif key_findings is not None:
            report.refresh_from_db()
            existing = ""
            if hasattr(report, "ai_summary") and report.ai_summary:
                existing = report.ai_summary.summary or ""
            self._save_manual_summary(report, existing, key_findings)

        return report


class ReportChatSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=4000)


class UserExplorationReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserExplorationReport
        fields = (
            "id",
            "title",
            "prompt",
            "status",
            "context",
            "revision_notes",
            "narrative",
            "sections",
            "pdf_file",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "status",
            "narrative",
            "sections",
            "pdf_file",
            "error_message",
            "created_at",
            "updated_at",
        )


class UserExplorationGenerateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    prompt = serializers.CharField()
    context = serializers.DictField(required=False)


class UserExplorationRefineSerializer(serializers.Serializer):
    revision_notes = serializers.CharField()
