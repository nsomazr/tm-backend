from django.urls import path

from .views import (
    ContextualReportsView,
    ReportAdminAiAssistView,
    ReportAdminDetailView,
    ReportAdminGeneratePdfView,
    ReportAdminView,
    ReportChatView,
    ReportDetailView,
    ReportDownloadView,
    ReportListView,
    UserExplorationDownloadView,
    UserExplorationExportPdfView,
    UserExplorationGenerateView,
    UserExplorationRefineView,
    UserExplorationReportViewSet,
)

exploration_list = UserExplorationReportViewSet.as_view({"get": "list"})
exploration_detail = UserExplorationReportViewSet.as_view({"get": "retrieve", "delete": "destroy"})

urlpatterns = [
    path("", ReportListView.as_view(), name="report-list"),
    path("contextual/", ContextualReportsView.as_view(), name="report-contextual"),
    path("exploration/", exploration_list, name="exploration-report-list"),
    path("exploration/generate/", UserExplorationGenerateView.as_view(), name="exploration-report-generate"),
    path("exploration/<int:pk>/", exploration_detail, name="exploration-report-detail"),
    path("exploration/<int:pk>/refine/", UserExplorationRefineView.as_view(), name="exploration-report-refine"),
    path("exploration/<int:pk>/export-pdf/", UserExplorationExportPdfView.as_view(), name="exploration-report-export"),
    path("exploration/<int:pk>/download/", UserExplorationDownloadView.as_view(), name="exploration-report-download"),
    path("admin/", ReportAdminView.as_view(), name="report-admin-list"),
    path("admin/ai-assist/", ReportAdminAiAssistView.as_view(), name="report-admin-ai-assist"),
    path("admin/<slug:slug>/generate-pdf/", ReportAdminGeneratePdfView.as_view(), name="report-admin-generate-pdf"),
    path("admin/<slug:slug>/", ReportAdminDetailView.as_view(), name="report-admin-detail"),
    path("<slug:slug>/chat/", ReportChatView.as_view(), name="report-chat"),
    path("<slug:slug>/", ReportDetailView.as_view(), name="report-detail"),
    path("<slug:slug>/download/", ReportDownloadView.as_view(), name="report-download"),
]
