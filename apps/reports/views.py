import logging

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework import generics, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsMineralManagerOrAdmin
from apps.analytics.credits import InsufficientAssistantCredits, consume_assistant_credit, get_assistant_credit_quota
from apps.minerals.permissions import get_managed_mineral_ids, user_can_manage_mineral

from .access import get_subscription_download_quota, record_subscription_download, user_can_download_report, user_has_report_detail_access
from .ai_serializers import ReportAiAssistSerializer
from .ai_service import generate_report_writing_assist
from .article_service import sync_report_article_body
from .context_extraction import extract_text_from_upload
from .contextual import find_contextual_reports
from .exploration_pdf_service import save_exploration_report_pdf
from .exploration_service import generate_exploration_draft
from .models import Report, ReportChatThread, UserExplorationReport
from .pdf_service import ensure_report_pdf
from .rag_service import answer_report_chat, ensure_report_indexed, retrieve_report_chunks
from .serializers import (
    ReportAdminSerializer,
    ReportChatSerializer,
    ReportSerializer,
    UserExplorationGenerateSerializer,
    UserExplorationRefineSerializer,
    UserExplorationReportSerializer,
)
from .web_search import append_web_references, search_web_for_report, web_search_unavailable_reason
from .tasks import generate_report_summary, index_report_pdf

logger = logging.getLogger(__name__)


def _admin_report_queryset(user):
    qs = (
        Report.objects.all()
        .select_related("mineral", "region")
        .prefetch_related("ai_summary", "layers", "boundaries", "allowed_plans")
    )
    managed = get_managed_mineral_ids(user)
    if managed is not None:
        qs = qs.filter(mineral_id__in=managed)
    return qs


def _post_save_report(report, *, manual_summary: bool, pdf_changed: bool, regenerate_pdf: bool = False):
    if manual_summary:
        if not report.pdf_file:
            ensure_report_pdf(report)
        sync_report_article_body(report, force=True)
        return
    if pdf_changed:
        # Uploaded PDFs are the report — index for chat/search only, do not rewrite as AI text.
        if report.source_type == Report.SourceType.UPLOADED:
            from .rag_service import index_report_pdf

            try:
                index_report_pdf(report.id)
            except Exception:
                logger.exception("Synchronous PDF indexing failed for report %s", report.id)
                index_report_pdf.delay(report.id)
        else:
            generate_report_summary.delay(report.id)
            index_report_pdf.delay(report.id)
    elif regenerate_pdf:
        ensure_report_pdf(report, force=True)
        sync_report_article_body(report, force=True)
    else:
        sync_report_article_body(report)


class ReportListView(generics.ListAPIView):
    queryset = Report.objects.filter(is_active=True).select_related("mineral", "region")
    serializer_class = ReportSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["mineral", "region"]
    search_fields = ["title", "description"]

    def get_queryset(self):
        qs = super().get_queryset()
        mineral = self.request.query_params.get("mineral")
        region = self.request.query_params.get("region")
        if mineral:
            if mineral.isdigit():
                qs = qs.filter(mineral_id=int(mineral))
            else:
                qs = qs.filter(mineral__slug=mineral)
        if region:
            if region.isdigit():
                qs = qs.filter(region_id=int(region))
        return qs.prefetch_related(
            "ai_summary",
            "purchases",
            "layers",
            "boundaries",
            "allowed_plans",
        )

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
        .prefetch_related("ai_summary", "purchases", "layers", "boundaries", "allowed_plans")
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


class ContextualReportsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        lat = request.query_params.get("lat")
        lng = request.query_params.get("lng")
        layer_ids_raw = request.query_params.get("layer_ids", "")
        layer_ids = []
        if layer_ids_raw:
            for part in layer_ids_raw.split(","):
                part = part.strip()
                if part.isdigit():
                    layer_ids.append(int(part))

        boundary_id = request.query_params.get("boundary_id")
        results = find_contextual_reports(
            lat=float(lat) if lat else None,
            lng=float(lng) if lng else None,
            mineral_slug=request.query_params.get("mineral_slug", ""),
            layer_ids=layer_ids or None,
            boundary_id=int(boundary_id) if boundary_id and boundary_id.isdigit() else None,
            country_code=request.query_params.get("country_code", "TZ"),
            limit=int(request.query_params.get("limit", 6)),
            request=request,
        )
        return Response({"results": results})


class ReportAdminView(generics.ListCreateAPIView):
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]

    def get_queryset(self):
        return _admin_report_queryset(self.request.user)

    def perform_create(self, serializer):
        mineral = serializer.validated_data.get("mineral")
        if mineral and not user_can_manage_mineral(self.request.user, mineral.pk):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You cannot create reports for this commodity.")

        if serializer.validated_data.get("pdf_file"):
            serializer.validated_data.setdefault("source_type", Report.SourceType.UPLOADED)
            serializer.validated_data.setdefault("report_format", Report.ReportFormat.PDF)

        report = serializer.save(created_by=self.request.user)
        manual = serializer.context.get("manual_summary_saved")
        _post_save_report(report, manual_summary=manual, pdf_changed=bool(report.pdf_file))


class ReportAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ReportAdminSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    lookup_field = "slug"

    def get_queryset(self):
        return _admin_report_queryset(self.request.user)

    def perform_update(self, serializer):
        mineral = serializer.validated_data.get("mineral")
        if mineral and not user_can_manage_mineral(self.request.user, mineral.id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You cannot edit reports for this commodity.")

        pdf_changed = "pdf_file" in serializer.validated_data
        regenerate = self.request.data.get("regenerate_pdf") in (True, "true", "1", 1)
        report = serializer.save()
        manual = serializer.context.get("manual_summary_saved")
        _post_save_report(
            report,
            manual_summary=manual,
            pdf_changed=pdf_changed,
            regenerate_pdf=regenerate,
        )


class ReportAdminGeneratePdfView(APIView):
    permission_classes = [IsMineralManagerOrAdmin]

    def post(self, request, slug):
        try:
            report = _admin_report_queryset(request.user).get(slug=slug)
        except Report.DoesNotExist:
            raise Http404

        force = request.data.get("force") in (True, "true", "1", 1)
        try:
            ensure_report_pdf(report, force=force)
            sync_report_article_body(report, force=True)
        except Exception as exc:
            return Response(
                {"detail": f"PDF generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"detail": "PDF ready.", "slug": report.slug})


class ReportAdminAiAssistView(APIView):
    permission_classes = [IsMineralManagerOrAdmin]

    def post(self, request):
        serializer = ReportAiAssistSerializer.from_request(request)
        serializer.is_valid(raise_exception=True)

        context_text = (serializer.validated_data.get("context_text") or "").strip()
        context_file = request.FILES.get("context_file")
        if context_file:
            extracted = extract_text_from_upload(context_file)
            if extracted:
                uploaded = f"Uploaded reference document ({context_file.name}):\n{extracted}"
                context_text = f"{context_text}\n\n{uploaded}".strip() if context_text else uploaded

        instruction = (serializer.validated_data.get("instruction") or "").strip()
        metadata = serializer.validated_metadata()
        web_search_requested = serializer.validated_enable_web_search()
        web_sources = []
        web_search_warning = None

        if web_search_requested:
            unavailable = web_search_unavailable_reason()
            if unavailable:
                web_search_warning = unavailable
            else:
                web_result = search_web_for_report(metadata, instruction)
                web_sources = web_result.sources
                if web_result.context_text:
                    context_text = (
                        f"{context_text}\n\n{web_result.context_text}".strip()
                        if context_text
                        else web_result.context_text
                    )
                elif not web_sources:
                    web_search_warning = (
                        "Web search returned no results. Try a more specific prompt or check your Tavily account."
                    )

        try:
            draft, model_used = generate_report_writing_assist(
                metadata=metadata,
                context_text=context_text,
                messages=serializer.validated_chat_messages(),
                current_draft=serializer.validated_current_draft(),
            )
        except Exception as exc:
            return Response(
                {"detail": f"Report assistant failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if web_sources and draft.get("executive_summary"):
            draft["executive_summary"] = append_web_references(
                draft["executive_summary"],
                web_sources,
            )

        if draft.get("key_findings"):
            from .report_text_utils import filter_report_findings

            draft["key_findings"] = filter_report_findings(
                [str(item).strip() for item in draft["key_findings"] if str(item).strip()]
            )

        return Response(
            {
                "executive_summary": draft.get("executive_summary") or "",
                "key_findings": draft.get("key_findings") or [],
                "assistant_reply": draft.get("assistant_reply") or "",
                "model_used": model_used,
                "web_search": {
                    "requested": web_search_requested,
                    "used": bool(web_sources),
                    "source_count": len(web_sources),
                    "warning": web_search_warning,
                },
            }
        )


class ReportChatView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        try:
            report = Report.objects.get(slug=slug, is_active=True)
        except Report.DoesNotExist:
            raise Http404

        if report.source_type != Report.SourceType.UPLOADED:
            return Response({"messages": []})

        if not user_has_report_detail_access(request.user, report):
            return Response({"detail": "Full report access required."}, status=status.HTTP_403_FORBIDDEN)

        thread, _ = ReportChatThread.objects.get_or_create(report=report, user=request.user)
        return Response({"messages": thread.messages or []})

    def post(self, request, slug):
        try:
            report = Report.objects.get(slug=slug, is_active=True)
        except Report.DoesNotExist:
            raise Http404

        if report.source_type != Report.SourceType.UPLOADED or not report.pdf_file:
            return Response({"detail": "PDF chat is only available for uploaded reports."}, status=status.HTTP_400_BAD_REQUEST)

        if not user_has_report_detail_access(request.user, report):
            return Response({"detail": "Full report access required."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ReportChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data["message"].strip()

        quota = get_assistant_credit_quota(request, user=request.user)
        if not quota.get("unlimited") and (quota.get("remaining") or 0) < 1:
            return Response(
                {"detail": "Insufficient assistant credits.", "assistant_credits": quota},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        thread, _ = ReportChatThread.objects.get_or_create(report=report, user=request.user)
        history = list(thread.messages or [])
        ensure_report_indexed(report)
        chunks = retrieve_report_chunks(report, message)
        try:
            reply, model_used = answer_report_chat(message, chunks, history)
        except Exception as exc:
            return Response(
                {"detail": str(exc) or "Report chat unavailable right now."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            from apps.analytics.models import AssistantCreditUsage
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.REPORT_CHAT,
                user=request.user,
                credits=1,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {"detail": "Insufficient assistant credits.", "assistant_credits": exc.quota},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply, "model_used": model_used})
        thread.messages = history[-40:]
        thread.save(update_fields=["messages", "updated_at"])

        return Response(
            {
                "reply": reply,
                "model_used": model_used,
                "citations": [
                    {"page_number": chunk.page_number, "excerpt": chunk.text[:240]}
                    for chunk in chunks[:3]
                ],
                "messages": thread.messages,
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


class UserExplorationReportViewSet(viewsets.ModelViewSet):
    serializer_class = UserExplorationReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserExplorationReport.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status=UserExplorationReport.Status.DRAFT)

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use POST /exploration/generate/ to create exploration reports."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class UserExplorationGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UserExplorationGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            from apps.analytics.models import AssistantCreditUsage
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.EXPLORATION_GENERATE,
                user=request.user,
                credits=3,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {"detail": "Insufficient assistant credits.", "assistant_credits": exc.quota},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        record = UserExplorationReport.objects.create(
            user=request.user,
            title=serializer.validated_data.get("title", ""),
            prompt=serializer.validated_data["prompt"],
            context=serializer.validated_data.get("context") or {},
            status=UserExplorationReport.Status.DRAFT,
        )
        generate_exploration_draft(record)
        record.refresh_from_db()
        return Response(
            UserExplorationReportSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )


class UserExplorationRefineView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            record = UserExplorationReport.objects.get(pk=pk, user=request.user)
        except UserExplorationReport.DoesNotExist:
            raise Http404

        serializer = UserExplorationRefineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            from apps.analytics.models import AssistantCreditUsage
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.EXPLORATION_REFINE,
                user=request.user,
                credits=1,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {"detail": "Insufficient assistant credits.", "assistant_credits": exc.quota},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        record.revision_notes = (
            f"{record.revision_notes}\n{serializer.validated_data['revision_notes']}".strip()
        )
        record.save(update_fields=["revision_notes", "updated_at"])
        generate_exploration_draft(record)
        record.refresh_from_db()
        return Response(UserExplorationReportSerializer(record).data)


class UserExplorationExportPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            record = UserExplorationReport.objects.get(pk=pk, user=request.user)
        except UserExplorationReport.DoesNotExist:
            raise Http404

        if record.status != UserExplorationReport.Status.READY:
            return Response({"detail": "Report is not ready for export."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from apps.analytics.models import AssistantCreditUsage
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.EXPLORATION_EXPORT,
                user=request.user,
                credits=5,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {"detail": "Insufficient assistant credits.", "assistant_credits": exc.quota},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            save_exploration_report_pdf(record)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        record.refresh_from_db()
        return Response(UserExplorationReportSerializer(record).data)


class UserExplorationDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            record = UserExplorationReport.objects.get(pk=pk, user=request.user)
        except UserExplorationReport.DoesNotExist:
            raise Http404

        if not record.pdf_file:
            return Response({"detail": "No PDF exported yet."}, status=status.HTTP_404_NOT_FOUND)

        filename = f"exploration-{record.id}.pdf"
        return FileResponse(
            record.pdf_file.open("rb"),
            as_attachment=True,
            filename=filename,
        )
