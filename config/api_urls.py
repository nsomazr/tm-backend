from django.urls import include, path

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("geography/", include("apps.geography.urls")),
    path("minerals/", include("apps.minerals.urls")),
    path("maps/", include("apps.maps.urls")),
    path("subscriptions/", include("apps.subscriptions.urls")),
    path("payments/", include("apps.payments.urls")),
    path("reports/", include("apps.reports.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("compliance/", include("apps.compliance.urls")),
    path("admin/", include("apps.accounts.admin_urls")),
]
