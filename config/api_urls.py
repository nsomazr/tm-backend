from django.urls import include, path

from config.media import serve_public_media

urlpatterns = [
    path("media/<path:path>", serve_public_media, name="public-media"),
    path("auth/", include("apps.accounts.urls")),
    path("geography/", include("apps.geography.urls")),
    path("minerals/", include("apps.minerals.urls")),
    path("maps/", include("apps.maps.urls")),
    path("subscriptions/", include("apps.subscriptions.urls")),
    path("payments/", include("apps.payments.urls")),
    path("reports/", include("apps.reports.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("compliance/", include("apps.compliance.urls")),
    path("ads/", include("apps.ads.urls")),
    path("marketplace/", include("apps.marketplace.urls")),
    path("admin/", include("apps.accounts.admin_urls")),
]
