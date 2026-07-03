from django.http import FileResponse, Http404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser, IsMineralManagerOrAdmin

from .access import get_subscription_download_quota, record_subscription_download, user_can_download_report
from .ai_serializers import ReportAiAssistSerializer
from .ai_service import generate_report_writing_assist
from .context_extraction import extract_text_from_upload
from .models import Report
from .pdf_service import ensure_report_pdf
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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated:
            context["download_quota"] = get_subscription_download_quota(user)
        context["preview_mode"] = "list"
        return context


class ReportDetailView(generics.RetrieveAPIView):
    queryset = (
        Report.objects.filter(is_active=True)
        .select_related("mineral", "region")
        .prefetch_related("ai_summary", "purchases")
    )
    serializer_class = ReportSerializer
    permission_classes = [AllowAny]
    lookup_field = "slug"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated:
            context["download_quota"] = get_subscription_download_quota(user)
        context["preview_mode"] = "detail"
        return context


class ReportAdminView(generics.ListCreateAPIView):
    queryset = Report.objects.all().select_related("mineral", "region").prefetch_related("ai_summary")
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]

    def perform_create(self, serializer):
        report = serializer.save(created_by=self.request.user)
        if serializer.context.get("manual_summary_saved"):
            if not report.pdf_file:
                ensure_report_pdf(report)
            return
        generate_report_summary.delay(report.id)


class ReportAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Report.objects.all().select_related("mineral", "region").prefetch_related("ai_summary")
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    lookup_field = "slug"

    def perform_update(self, serializer):
        report = serializer.save()
        if serializer.context.get("manual_summary_saved"):
            if not report.pdf_file:
                ensure_report_pdf(report)
            elif self.request.data.get("regenerate_pdf") in (True, "true", "1", 1):
                ensure_report_pdf(report, force=True)
            return
        if "pdf_file" in serializer.validated_data:
            generate_report_summary.delay(report.id)


class ReportAdminGeneratePdfView(APIView):
    permission_classes = [IsMineralManagerOrAdmin]

    def post(self, request, slug):
        try:
            report = Report.objects.get(slug=slug)
        except Report.DoesNotExist:
            raise Http404

        force = request.data.get("force") in (True, "true", "1", 1)
        try:
            ensure_report_pdf(report, force=force)
        except Exception as exc:
            return Response(
                {"detail": f"PDF generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"detail": "PDF ready.", "slug": report.slug})


class ReportAdminAiAssistView(APIView):
    """Draft or refine written report content with AI (+ optional uploaded context)."""

    permission_classes = [IsMineralManagerOrAdmin]

    def post(self, request):
        serializer = ReportAiAssistSerializer.from_request(request)
        serializer.is_valid(raise_exception=True)

        context_text = (serializer.validated_data.get("context_text") or "").strip()
        context_file = request.FILES.get("context_file")
        if context_file:
            extracted = extract_text_from_upload(context_file)
            if extracted:
                context_text = f"{context_text}\n\n{extracted}".strip() if context_text else extracted

        try:
            draft, model_used = generate_report_writing_assist(
                metadata=serializer.validated_metadata(),
                context_text=context_text,
                messages=serializer.validated_chat_messages(),
                current_draft=serializer.validated_current_draft(),
            )
        except Exception as exc:
            return Response(
                {"detail": f"Report assistant failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "executive_summary": draft.get("executive_summary") or "",
                "key_findings": draft.get("key_findings") or [],
                "assistant_reply": draft.get("assistant_reply") or "",
                "model_used": model_used,
            }
        )


class ReportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        try:
            report = Report.objects.get(slug=slug, is_active=True)
        except Report.DoesNotExist:
            raise Http404

        can_download, source = user_can_download_report(request.user, report)
        if not can_download:
            quota = get_subscription_download_quota(request.user)
            payload = {"detail": "Download not available. Subscribe, use your included downloads, or purchase this report."}
            if quota:
                payload["download_quota"] = quota
            return Response(payload, status=status.HTTP_403_FORBIDDEN)

        if not report.pdf_file:
            try:
                ensure_report_pdf(report)
                report.refresh_from_db()
            except Exception:
                return Response(
                    {"detail": "No PDF available and automatic generation failed."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        if not report.pdf_file:
            return Response({"detail": "No PDF available."}, status=status.HTTP_404_NOT_FOUND)

        if source == "subscription":
            record_subscription_download(request.user, report)

        filename = f"{report.slug}.pdf"
        return FileResponse(
            report.pdf_file.open("rb"),
            as_attachment=True,
            filename=filename,
        )
