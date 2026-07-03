from django.urls import path

from .views import (
    AcceptTermsView,
    ActiveTermsView,
    AuditLogListView,
    LicenseAgreementDetailView,
    LicenseAgreementListView,
)

urlpatterns = [
    path("terms/", ActiveTermsView.as_view(), name="active-terms"),
    path("terms/accept/", AcceptTermsView.as_view(), name="accept-terms"),
    path("licenses/", LicenseAgreementListView.as_view(), name="license-list"),
    path("licenses/<int:pk>/", LicenseAgreementDetailView.as_view(), name="license-detail"),
    path("audit-logs/", AuditLogListView.as_view(), name="audit-logs"),
]
