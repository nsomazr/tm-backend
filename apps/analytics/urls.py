from django.urls import path

from .views import (
    AdminPlatformAnalyticsView,
    AreaInsightsView,
    HotspotAnalyticsView,
    InvestorDashboardView,
    MineralSearchInsightsView,
)

urlpatterns = [
    path("hotspots/", HotspotAnalyticsView.as_view(), name="analytics-hotspots"),
    path("investor/", InvestorDashboardView.as_view(), name="analytics-investor"),
    path("admin/", AdminPlatformAnalyticsView.as_view(), name="analytics-admin"),
    path("search-insights/", MineralSearchInsightsView.as_view(), name="analytics-search-insights"),
    path("area-insights/", AreaInsightsView.as_view(), name="analytics-area-insights"),
]
