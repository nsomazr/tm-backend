from rest_framework import serializers

from apps.maps.localization import get_request_locale, localized_name

from .models import DownloadPurchase, SubscriptionPlan, UserSubscription


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    included_mineral_names = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "billing_cycle",
            "price",
            "currency",
            "included_minerals",
            "included_mineral_names",
            "is_active",
        )

    def get_included_mineral_names(self, obj):
        locale = get_request_locale(self.context.get("request"))
        return [localized_name(m, locale) for m in obj.included_minerals.all()]


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan_detail = SubscriptionPlanSerializer(source="plan", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    days_until_expiry = serializers.IntegerField(read_only=True)

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
            "created_at",
        )
        read_only_fields = ("status", "start_date", "end_date", "created_at")


class DownloadPurchaseSerializer(serializers.ModelSerializer):
    report_title = serializers.CharField(source="report.title", read_only=True)

    class Meta:
        model = DownloadPurchase
        fields = (
            "id",
            "report",
            "report_title",
            "amount_paid",
            "currency",
            "purchased_at",
        )
