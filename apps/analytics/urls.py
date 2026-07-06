from django.urls import path

from .views import (
    AdminPlatformAnalyticsView,
    AreaInsightsView,
    AssistantChatHistoryView,
    AssistantCreditsView,
    HotspotAnalyticsView,
    InvestorDashboardView,
    MineralBoundaryCoverageView,
    MineralCatalogView,
    MineralSearchInsightsView,
    SearchContextInsightsView,
    TerraAssistantChatView,
    TerraInsightExportView,
)

urlpatterns = [
    path("hotspots/", HotspotAnalyticsView.as_view(), name="analytics-hotspots"),
    path("investor/", InvestorDashboardView.as_view(), name="analytics-investor"),
    path("admin/", AdminPlatformAnalyticsView.as_view(), name="analytics-admin"),
    path("search-insights/", MineralSearchInsightsView.as_view(), name="analytics-search-insights"),
    path("mineral-catalog/", MineralCatalogView.as_view(), name="analytics-mineral-catalog"),
    path("minerals/<slug:slug>/coverage/", MineralBoundaryCoverageView.as_view(), name="analytics-mineral-coverage"),
    path("search-context-insights/", SearchContextInsightsView.as_view(), name="analytics-search-context-insights"),
    path("area-insights/", AreaInsightsView.as_view(), name="analytics-area-insights"),
    path("assistant/credits/", AssistantCreditsView.as_view(), name="analytics-assistant-credits"),
    path("assistant/history/", AssistantChatHistoryView.as_view(), name="analytics-assistant-history"),
    path("assistant/chat/", TerraAssistantChatView.as_view(), name="analytics-assistant-chat"),
    path("assistant/export-report/", TerraInsightExportView.as_view(), name="analytics-assistant-export"),
]
