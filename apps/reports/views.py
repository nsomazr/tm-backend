from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser, IsMineralManagerOrAdmin
from apps.payments.models import PaymentOrder
from apps.payments.serializers import CheckoutSerializer
from apps.subscriptions.models import DownloadPurchase

from .models import Report
from .serializers import ReportAdminSerializer, ReportSerializer
from .tasks import generate_report_summary


class ReportListView(generics.ListAPIView):
    queryset = Report.objects.filter(is_active=True).select_related("mineral", "region")
    serializer_class = ReportSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["mineral", "region"]
    search_fields = ["title", "description"]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.prefetch_related("ai_summary", "purchases")


class ReportDetailView(generics.RetrieveAPIView):
    queryset = Report.objects.filter(is_active=True).select_related("mineral", "region")
    serializer_class = ReportSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"


class ReportAdminView(generics.ListCreateAPIView):
    queryset = Report.objects.all().select_related("mineral", "region")
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]

    def perform_create(self, serializer):
        report = serializer.save(created_by=self.request.user)
        generate_report_summary.delay(report.id)


class ReportAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Report.objects.all()
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    lookup_field = "slug"

    def perform_update(self, serializer):
        report = serializer.save()
        if "pdf_file" in serializer.validated_data:
            generate_report_summary.delay(report.id)


class ReportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        try:
            report = Report.objects.get(slug=slug, is_active=True)
        except Report.DoesNotExist:
            raise Http404

        has_access = (
            request.user.has_paid_access
            or DownloadPurchase.objects.filter(user=request.user, report=report).exists()
        )
        if not has_access:
            return Response(
                {"detail": "Purchase required to download this report."},
                status=status.HTTP403_FORBIDDEN,
            )

        if not report.pdf_file:
            return Response({"detail": "No PDF available."}, status=status.HTTP_404_NOT_FOUND)

        return FileResponse(report.pdf_file.open("rb"), as_attachment=True, filename=report.pdf_file.name)
