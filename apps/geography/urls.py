from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminBoundaryGeologyDetailView,
    AdminBoundaryGeologyDocumentView,
    AdminBoundaryImportStatusView,
    AdminBoundaryImportView,
    AdminBoundaryItemsView,
    AdminBoundaryListView,
    AdminGeoReferenceDetailView,
    AdminGeoReferenceGeoJsonView,
    AdminGeoReferenceListCreateView,
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
    path("admin/boundaries/items/", AdminBoundaryItemsView.as_view(), name="admin-boundary-items"),
    path(
        "admin/boundaries/<int:boundary_id>/geology/",
        AdminBoundaryGeologyDetailView.as_view(),
        name="admin-boundary-geology",
    ),
    path(
        "admin/boundaries/<int:boundary_id>/geology/documents/",
        AdminBoundaryGeologyDocumentView.as_view(),
        name="admin-boundary-geology-documents",
    ),
    path(
        "admin/boundaries/<int:boundary_id>/geology/documents/<int:document_id>/",
        AdminBoundaryGeologyDocumentView.as_view(),
        name="admin-boundary-geology-document-delete",
    ),
    path(
        "admin/geo-references/",
        AdminGeoReferenceListCreateView.as_view(),
        name="admin-geo-reference-list",
    ),
    path(
        "admin/geo-references/geojson/",
        AdminGeoReferenceGeoJsonView.as_view(),
        name="admin-geo-reference-geojson-all",
    ),
    path(
        "admin/geo-references/<int:pk>/",
        AdminGeoReferenceDetailView.as_view(),
        name="admin-geo-reference-detail",
    ),
    path(
        "admin/geo-references/<int:pk>/geojson/",
        AdminGeoReferenceGeoJsonView.as_view(),
        name="admin-geo-reference-geojson",
    ),
    path("", include(router.urls)),
]
