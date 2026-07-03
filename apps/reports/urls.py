from django.urls import path

from .views import (
    ReportAdminAiAssistView,
    ReportAdminDetailView,
    ReportAdminGeneratePdfView,
    ReportAdminView,
    ReportDetailView,
    ReportDownloadView,
    ReportListView,
)

urlpatterns = [
    path("", ReportListView.as_view(), name="report-list"),
    path("admin/", ReportAdminView.as_view(), name="report-admin-list"),
    path("admin/ai-assist/", ReportAdminAiAssistView.as_view(), name="report-admin-ai-assist"),
    path("admin/<slug:slug>/generate-pdf/", ReportAdminGeneratePdfView.as_view(), name="report-admin-generate-pdf"),
    path("admin/<slug:slug>/", ReportAdminDetailView.as_view(), name="report-admin-detail"),
    path("<slug:slug>/", ReportDetailView.as_view(), name="report-detail"),
    path("<slug:slug>/download/", ReportDownloadView.as_view(), name="report-download"),
]
