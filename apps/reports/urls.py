from django.urls import path

from .views import (
    ReportAdminDetailView,
    ReportAdminView,
    ReportDetailView,
    ReportDownloadView,
    ReportListView,
)

urlpatterns = [
    path("", ReportListView.as_view(), name="report-list"),
    path("admin/", ReportAdminView.as_view(), name="report-admin-list"),
    path("admin/<slug:slug>/", ReportAdminDetailView.as_view(), name="report-admin-detail"),
    path("<slug:slug>/", ReportDetailView.as_view(), name="report-detail"),
    path("<slug:slug>/download/", ReportDownloadView.as_view(), name="report-download"),
]
