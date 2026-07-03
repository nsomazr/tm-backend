from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import DownloadPurchase, SubscriptionPlan, UserSubscription
from .serializers import (
    DownloadPurchaseSerializer,
    SubscriptionPlanSerializer,
    UserSubscriptionSerializer,
)


class SubscriptionPlanListView(generics.ListAPIView):
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
            return Response({"detail": "No active subscription."}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


class MyPurchasesView(generics.ListAPIView):
    serializer_class = DownloadPurchaseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DownloadPurchase.objects.filter(user=self.request.user).select_related("report")


class AdminSubscriptionListView(generics.ListAPIView):
    queryset = UserSubscription.objects.select_related("user", "plan").order_by("-created_at")
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["status", "plan"]
