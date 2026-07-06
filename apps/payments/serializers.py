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
    description = serializers.SerializerMethodField()
    invoice_number = serializers.SerializerMethodField()
    invoice_issued_at = serializers.SerializerMethodField()
    subscription_detail = serializers.SerializerMethodField()
    report_detail = serializers.SerializerMethodField()
    license_detail = serializers.SerializerMethodField()
    aerial_detail = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    activation_source = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = (
            "id",
            "user",
            "user_email",
            "user_username",
            "order_type",
            "description",
            "amount",
            "currency",
            "status",
            "merchant_reference",
            "account_number",
            "order_tracking_id",
            "payment_provider",
            "payment_method",
            "msisdn",
            "subscription_detail",
            "report_detail",
            "license_detail",
            "aerial_detail",
            "invoice_number",
            "invoice_issued_at",
            "activation_source",
            "gateway_response",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_description(self, obj):
        from .services import order_description

        return order_description(obj)

    def get_invoice_number(self, obj):
        invoice = getattr(obj, "invoice", None)
        return invoice.invoice_number if invoice else None

    def get_invoice_issued_at(self, obj):
        invoice = getattr(obj, "invoice", None)
        return invoice.issued_at if invoice else None

    def get_subscription_detail(self, obj):
        if not obj.subscription_id:
            return None
        subscription = obj.subscription
        plan = subscription.plan
        return {
            "id": subscription.id,
            "status": subscription.status,
            "plan_name": plan.name,
            "plan_slug": plan.slug,
            "billing_cycle": plan.billing_cycle,
            "start_date": subscription.start_date,
            "end_date": subscription.end_date,
        }

    def get_report_detail(self, obj):
        if not obj.report_id:
            return None
        report = obj.report
        return {
            "id": report.id,
            "title": report.title,
            "slug": report.slug,
        }

    def get_license_detail(self, obj):
        if not obj.license_agreement_id:
            return None
        license_agreement = obj.license_agreement
        return {
            "id": license_agreement.id,
            "company_name": license_agreement.company_name,
            "contact_name": license_agreement.contact_name,
            "status": license_agreement.status,
        }

    def get_aerial_detail(self, obj):
        aerial = (obj.gateway_response or {}).get("aerial")
        return aerial if aerial else None

    def get_payment_method(self, obj):
        if obj.payment_provider == "simulated":
            return "simulated"
        gateway = obj.gateway_response or {}
        create_payment = gateway.get("create_payment")
        if isinstance(create_payment, dict):
            payload = create_payment.get("data") if isinstance(create_payment.get("data"), dict) else create_payment
            payment_type = payload.get("payment_type")
            if payment_type:
                return payment_type
        if obj.msisdn:
            return "mobile_money"
        return None

    def get_activation_source(self, obj):
        activation = (obj.gateway_response or {}).get("activation")
        if not isinstance(activation, dict):
            return None
        if activation.get("manual"):
            return "manual_admin"
        if activation.get("webhook") or activation.get("event"):
            return "webhook"
        return "gateway"


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
    lat = serializers.FloatField(required=False)
    lng = serializers.FloatField(required=False)
    zoom = serializers.IntegerField(required=False, min_value=3, max_value=18)
    extra_km2 = serializers.FloatField(required=False, min_value=1)
    msisdn = serializers.CharField(required=False, allow_blank=True, max_length=20)
    payment_method = serializers.ChoiceField(
        choices=[("mobile_money", "Mobile money"), ("card", "Card")],
        required=False,
        default="mobile_money",
    )
    card_brand = serializers.ChoiceField(
        choices=[("visa", "Visa"), ("mastercard", "Mastercard")],
        required=False,
    )
    cardholder_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    billing_email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs):
        order_type = attrs["order_type"]
        if order_type == PaymentOrder.OrderType.SUBSCRIPTION and not attrs.get("plan_id"):
            raise serializers.ValidationError({"plan_id": "Required for subscription checkout."})
        if order_type == PaymentOrder.OrderType.DOWNLOAD and not attrs.get("report_id"):
            raise serializers.ValidationError({"report_id": "Required for report checkout."})
        if order_type == PaymentOrder.OrderType.LICENSE and not attrs.get("license_id"):
            raise serializers.ValidationError({"license_id": "Required for license checkout."})
        if order_type == PaymentOrder.OrderType.AERIAL:
            for field in ("lat", "lng", "extra_km2"):
                if attrs.get(field) is None:
                    raise serializers.ValidationError({field: f"Required for analysis extension checkout."})
        if attrs.get("payment_method") == "mobile_money" and not attrs.get("msisdn"):
            # msisdn can come from user profile at checkout time
            pass
        return attrs
