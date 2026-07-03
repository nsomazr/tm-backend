import uuid

from django.conf import settings
from django.db.models import Count, Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser, IsSuperAdmin
from apps.compliance.models import LicenseAgreement
from apps.reports.models import Report
from apps.subscriptions.models import SubscriptionPlan, UserSubscription

from .models import Invoice, PaymentOrder
from .selcom import selcom_is_configured
from .serializers import (
    AdminPaymentOrderSerializer,
    CheckoutSerializer,
    InvoiceSerializer,
    PaymentOrderSerializer,
)
from .services import activate_order, refresh_order_status, start_selcom_card_checkout, start_selcom_checkout


def _build_checkout_order(request, data):
    order_type = data["order_type"]
    user = request.user
    amount = 0
    currency = "TZS"
    subscription = None
    report = None
    license_agreement = None

    if order_type == PaymentOrder.OrderType.SUBSCRIPTION:
        plan = SubscriptionPlan.objects.get(id=data["plan_id"], is_active=True)
        amount = plan.price
        currency = plan.currency
        subscription = UserSubscription.objects.create(
            user=user,
            plan=plan,
            status=UserSubscription.Status.PENDING,
        )

    elif order_type == PaymentOrder.OrderType.DOWNLOAD:
        report = Report.objects.get(id=data["report_id"], is_active=True)
        amount = report.price
        currency = report.currency

    elif order_type == PaymentOrder.OrderType.LICENSE:
        license_agreement = LicenseAgreement.objects.get(id=data["license_id"])
        amount = license_agreement.price
        currency = license_agreement.currency

    merchant_reference = uuid.uuid4().hex
    order = PaymentOrder.objects.create(
        user=user,
        order_type=order_type,
        amount=amount,
        currency=currency,
        merchant_reference=merchant_reference,
        account_number=merchant_reference,
        subscription=subscription,
        report=report,
        license_agreement=license_agreement,
    )
    return order


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        order = _build_checkout_order(request, data)
        payment_method = data.get("payment_method", "mobile_money")

        if selcom_is_configured():
            if payment_method == "card":
                try:
                    order, gateway_url = start_selcom_card_checkout(order, user)
                except Exception as exc:
                    order.status = PaymentOrder.Status.FAILED
                    order.gateway_response = {"error": str(exc)}
                    order.save(update_fields=["status", "gateway_response", "updated_at"])
                    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

                return Response({
                    "order": PaymentOrderSerializer(order).data,
                    "payment_provider": "selcom",
                    "payment_method": "card",
                    "merchant_reference": order.merchant_reference,
                    "message": "Continue to the secure payment page to pay by card.",
                    "redirect_url": gateway_url,
                })

            msisdn = (data.get("msisdn") or user.phone or "").strip()
            if not msisdn:
                return Response(
                    {"detail": "Mobile number (msisdn) is required for Selcom payment."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                start_selcom_checkout(order, user, msisdn)
            except Exception as exc:
                order.status = PaymentOrder.Status.FAILED
                order.gateway_response = {"error": str(exc)}
                order.save(update_fields=["status", "gateway_response", "updated_at"])
                return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

            return Response({
                "order": PaymentOrderSerializer(order).data,
                "payment_provider": "selcom",
                "payment_method": "mobile_money",
                "merchant_reference": order.merchant_reference,
                "message": "Check your phone to approve the mobile money payment.",
                "callback_url": f"{settings.FRONTEND_URL}/payment/callback?ref={order.merchant_reference}",
            })

        order.payment_provider = "simulated"
        order.save(update_fields=["payment_provider"])

        if not settings.PAYMENTS_SIMULATE:
            return Response(
                {
                    "detail": (
                        "Payment gateway is not configured. Add Selcom credentials to .env, "
                        "or set PAYMENTS_SIMULATE=true for local testing only."
                    ),
                    "code": "payment_not_configured",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        activate_order(order)
        return Response({
            "detail": "Payment simulated (PAYMENTS_SIMULATE=true).",
            "order": PaymentOrderSerializer(order).data,
            "payment_provider": "simulated",
            "redirect_url": f"{settings.FRONTEND_URL}/dashboard",
        })


class PaymentOrderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        try:
            order = PaymentOrder.objects.get(merchant_reference=reference)
        except PaymentOrder.DoesNotExist:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        is_owner = order.user_id == request.user.id
        is_admin = request.user.role in ("super_admin", "admin")
        if not is_owner and not is_admin:
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        if order.status == PaymentOrder.Status.PENDING:
            refresh_order_status(order)
            order.refresh_from_db()

        return Response(PaymentOrderSerializer(order).data)


class MyInvoicesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        invoices = Invoice.objects.filter(user=request.user).order_by("-issued_at")
        return Response(InvoiceSerializer(invoices, many=True).data)


class AdminRevenueView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        completed = PaymentOrder.objects.filter(status=PaymentOrder.Status.COMPLETED)
        total = completed.aggregate(total=Sum("amount"))["total"] or 0
        by_type = completed.values("order_type").annotate(
            total=Sum("amount"),
            count=Count("id"),
        )
        by_provider = completed.values("payment_provider").annotate(
            total=Sum("amount"),
            count=Count("id"),
        )
        pending_count = PaymentOrder.objects.filter(status=PaymentOrder.Status.PENDING).count()
        failed_count = PaymentOrder.objects.filter(status=PaymentOrder.Status.FAILED).count()
        recent = PaymentOrder.objects.select_related("user").order_by("-created_at")[:20]
        return Response({
            "total_revenue": total,
            "by_type": list(by_type),
            "by_provider": list(by_provider),
            "pending_count": pending_count,
            "failed_count": failed_count,
            "recent_orders": AdminPaymentOrderSerializer(recent, many=True).data,
        })


class AdminPaymentOrderListView(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = AdminPaymentOrderSerializer
    queryset = PaymentOrder.objects.select_related("user").all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["status", "order_type", "payment_provider", "user"]
    search_fields = ["merchant_reference", "order_tracking_id", "user__email", "user__username", "msisdn"]
    ordering_fields = ["created_at", "amount", "status"]
    ordering = ["-created_at"]


class AdminPaymentOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = AdminPaymentOrderSerializer
    queryset = PaymentOrder.objects.select_related("user").all()
    lookup_field = "merchant_reference"


class AdminRefreshOrderView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, reference):
        try:
            order = PaymentOrder.objects.get(merchant_reference=reference)
        except PaymentOrder.DoesNotExist:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        refresh_order_status(order)
        order.refresh_from_db()
        return Response(AdminPaymentOrderSerializer(order).data)


class AdminCompleteOrderView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, reference):
        try:
            order = PaymentOrder.objects.get(merchant_reference=reference)
        except PaymentOrder.DoesNotExist:
            return Response({"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        if order.status == PaymentOrder.Status.COMPLETED:
            return Response(AdminPaymentOrderSerializer(order).data)
        activate_order(order, {"manual": True, "by": request.user.id})
        order.refresh_from_db()
        return Response(AdminPaymentOrderSerializer(order).data)
