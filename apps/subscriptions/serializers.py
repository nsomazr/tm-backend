from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name
from apps.reports.access import get_subscription_download_quota
from apps.analytics.credits import get_assistant_credit_quota

from .localization import billing_cycle_label, localized_plan_text
from .models import DownloadPurchase, SubscriptionPlan, UserSubscription


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    included_mineral_names = serializers.SerializerMethodField()
    billing_cycle_label = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "billing_cycle",
            "billing_cycle_label",
            "price",
            "currency",
            "included_minerals",
            "included_mineral_names",
            "included_report_downloads",
            "included_assistant_credits",
            "includes_chat_history",
            "is_active",
        )

    def get_included_mineral_names(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return [localized_name(m, locale) for m in obj.included_minerals.all()]

    def get_billing_cycle_label(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return billing_cycle_label(obj.billing_cycle, locale)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        locale = get_request_locale(self.context.get("request"))
        data["name"] = localized_plan_text(instance, "name", locale)
        data["description"] = localized_plan_text(instance, "description", locale)
        return data


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_detail = SubscriptionPlanSerializer(source="plan", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)
    download_quota = serializers.SerializerMethodField()
    assistant_credits = serializers.SerializerMethodField()

    class Meta:
        model = UserSubscription
        fields = (
            "id",
            "plan",
            "plan_detail",
            "status",
            "start_date",
            "end_date",
            "auto_renew",
            "is_active",
            "days_until_expiry",
            "download_quota",
            "assistant_credits",
            "created_at",
        )
        read_only_fields = ("status", "start_date", "end_date", "created_at")

    def get_download_quota(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        return get_subscription_download_quota(request.user)

    def get_assistant_credits(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return get_assistant_credit_quota(request, request.user)


class DownloadPurchaseSerializer(serializers.ModelSerializer):
    report_title = serializers.CharField(source="report.title", read_only=True)
    report_slug = serializers.CharField(source="report.slug", read_only=True)
    source = serializers.SerializerMethodField()

    class Meta:
        model = DownloadPurchase
        fields = (
            "id",
            "report",
            "report_slug",
            "report_title",
            "amount_paid",
            "currency",
            "purchased_at",
            "source",
        )
        read_only_fields = (
            "id",
            "report",
            "report_slug",
            "report_title",
            "amount_paid",
            "currency",
            "purchased_at",
            "source",
        )

    def get_source(self, obj):
        return "purchase"


class MyReportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    report = serializers.IntegerField()
    report_slug = serializers.CharField()
    report_title = serializers.CharField()
    source = serializers.ChoiceField(choices=("purchase", "subscription"))
    purchased_at = serializers.DateTimeField(allow_null=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    currency = serializers.CharField(required=False, allow_null=True)
