from rest_framework import serializers

from .models import Invoice, PaymentOrder


class PaymentOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentOrder
        fields = (
            "id",
            "order_type",
            "amount",
            "currency",
            "status",
            "merchant_reference",
            "order_tracking_id",
            "payment_provider",
            "msisdn",
            "created_at",
        )
        read_only_fields = fields


class AdminPaymentOrderSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = PaymentOrder
        fields = (
            "id",
            "user",
            "user_email",
            "user_username",
            "order_type",
            "amount",
            "currency",
            "status",
            "merchant_reference",
            "order_tracking_id",
            "payment_provider",
            "msisdn",
            "gateway_response",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = (
            "id",
            "invoice_number",
            "amount",
            "currency",
            "description",
            "pdf_file",
            "issued_at",
        )


class CheckoutSerializer(serializers.Serializer):
    order_type = serializers.ChoiceField(choices=PaymentOrder.OrderType.choices)
    plan_id = serializers.IntegerField(required=False)
    report_id = serializers.IntegerField(required=False)
    license_id = serializers.IntegerField(required=False)
    msisdn = serializers.CharField(required=False, allow_blank=True, max_length=20)
    payment_method = serializers.ChoiceField(
        choices=[("mobile_money", "Mobile money"), ("card", "Card")],
        required=False,
        default="mobile_money",
    )

    def validate(self, attrs):
        order_type = attrs["order_type"]
        if order_type == PaymentOrder.OrderType.SUBSCRIPTION and not attrs.get("plan_id"):
            raise serializers.ValidationError({"plan_id": "Required for subscription checkout."})
        if order_type == PaymentOrder.OrderType.DOWNLOAD and not attrs.get("report_id"):
            raise serializers.ValidationError({"report_id": "Required for report checkout."})
        if order_type == PaymentOrder.OrderType.LICENSE and not attrs.get("license_id"):
            raise serializers.ValidationError({"license_id": "Required for license checkout."})
        if attrs.get("payment_method") == "mobile_money" and not attrs.get("msisdn"):
            # msisdn can come from user profile at checkout time
            pass
        return attrs
