from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminBoundaryImportStatusView,
    AdminBoundaryImportView,
    AdminBoundaryListView,
    CountryViewSet,
    RegionViewSet,
)

router = DefaultRouter()
router.register("countries", CountryViewSet, basename="country")
router.register("regions", RegionViewSet, basename="region")

urlpatterns = [
    path("admin/boundaries/import/", AdminBoundaryImportView.as_view(), name="admin-boundary-import"),
    path(
        "admin/boundaries/import/<str:task_id>/",
        AdminBoundaryImportStatusView.as_view(),
        name="admin-boundary-import-status",
    ),
    path("admin/boundaries/", AdminBoundaryListView.as_view(), name="admin-boundary-list"),
    path("", include(router.urls)),
]
