from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser
from apps.accounts.throttling import PublicCatalogThrottleMixin
from apps.analytics.credits import get_assistant_credit_quota
from apps.analytics.models import AssistantCreditUsage
from apps.reports.models import UserExplorationReport
from apps.reports.access import get_subscription_download_quota

from .models import DownloadPurchase, SubscriptionPlan, SubscriptionReportDownload, UserSubscription
from .serializers import (
    MyReportSerializer,
    SubscriptionPlanSerializer,
    UserSubscriptionSerializer,
)


class SubscriptionPlanListView(PublicCatalogThrottleMixin, generics.ListAPIView):
    queryset = SubscriptionPlan.objects.filter(is_active=True).prefetch_related("included_minerals")
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [AllowAny]


class SubscriptionPlanAdminView(generics.ListCreateAPIView):
    queryset = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsAdminUser]


class MySubscriptionView(generics.RetrieveAPIView):
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        from django.conf import settings

        today = timezone.now().date()
        qs = UserSubscription.objects.filter(
            user=self.request.user,
            status=UserSubscription.Status.ACTIVE,
            end_date__gte=today,
            payment_orders__status="completed",
        )
        if not getattr(settings, "PAYMENTS_SIMULATE", False):
            qs = qs.exclude(payment_orders__payment_provider="simulated")
        return qs.select_related("plan").order_by("-end_date").distinct().first()

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        if not obj:
            return Response(
                {
                    "id": None,
                    "plan": None,
                    "plan_detail": None,
                    "status": None,
                    "start_date": None,
                    "end_date": None,
                    "auto_renew": False,
                    "is_active": False,
                    "days_until_expiry": None,
                    "download_quota": get_subscription_download_quota(request.user),
                    "assistant_credits": get_assistant_credit_quota(request, request.user),
                    "created_at": None,
                }
            )
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


class MyPurchasesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        rows: list[dict] = []
        seen: set[int] = set()

        purchases = (
            DownloadPurchase.objects.filter(user=user)
            .select_related("report")
            .order_by("-purchased_at")
        )
        for purchase in purchases:
            seen.add(purchase.report_id)
            rows.append(
                {
                    "id": purchase.id,
                    "report": purchase.report_id,
                    "report_slug": purchase.report.slug,
                    "report_title": purchase.report.title,
                    "source": "purchase",
                    "purchased_at": purchase.purchased_at,
                    "amount_paid": purchase.amount_paid,
                    "currency": purchase.currency,
                    "can_download": True,
                }
            )

        downloads = (
            SubscriptionReportDownload.objects.filter(user=user)
            .select_related("report")
            .order_by("-downloaded_at")
        )
        for download in downloads:
            if download.report_id in seen:
                continue
            rows.append(
                {
                    "id": download.id,
                    "report": download.report_id,
                    "report_slug": download.report.slug,
                    "report_title": download.report.title,
                    "source": "subscription",
                    "purchased_at": download.downloaded_at,
                    "amount_paid": None,
                    "currency": None,
                    "can_download": True,
                }
            )

        insight_exports = (
            AssistantCreditUsage.objects.filter(
                user=user,
                kind=AssistantCreditUsage.Kind.REPORT_EXPORT,
            )
            .order_by("-created_at")[:100]
        )
        for export in insight_exports:
            rows.append(
                {
                    "id": export.id,
                    "report": 0,
                    "report_slug": "",
                    "report_title": "Terra insight area brief",
                    "source": "insight_export",
                    "purchased_at": export.created_at,
                    "amount_paid": None,
                    "currency": None,
                    "can_download": False,
                }
            )

        explorations = (
            UserExplorationReport.objects.filter(user=user)
            .exclude(status=UserExplorationReport.Status.DRAFT)
            .order_by("-created_at")[:100]
        )
        for exploration in explorations:
            rows.append(
                {
                    "id": exploration.id,
                    "report": exploration.id,
                    "report_slug": str(exploration.id),
                    "report_title": exploration.title or f"Exploration report #{exploration.id}",
                    "source": "exploration",
                    "purchased_at": exploration.created_at,
                    "amount_paid": None,
                    "currency": None,
                    "status": exploration.status,
                    "can_download": bool(
                        exploration.status == UserExplorationReport.Status.READY
                        and exploration.pdf_file
                    ),
                }
            )

        rows.sort(key=lambda row: row["purchased_at"], reverse=True)
        serializer = MyReportSerializer(rows, many=True)
        return Response(serializer.data)


class AdminSubscriptionListView(generics.ListAPIView):
    queryset = UserSubscription.objects.select_related("user", "plan").order_by("-created_at")
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["status", "plan"]
