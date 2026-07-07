from django.urls import path

from .views import AdAdminDetailView, AdAdminListCreateView, AdAdminStatsView, AdServeView, AdTrackView

urlpatterns = [
    path("serve/", AdServeView.as_view(), name="ad-serve"),
    path("track/", AdTrackView.as_view(), name="ad-track"),
    path("admin/stats/", AdAdminStatsView.as_view(), name="ad-admin-stats"),
    path("admin/", AdAdminListCreateView.as_view(), name="ad-admin-list"),
    path("admin/<int:pk>/", AdAdminDetailView.as_view(), name="ad-admin-detail"),
]
