from django.urls import path

from .views import (
    ListingDocumentCreateView,
    ListingDocumentDeleteView,
    ListingInquiryCreateView,
    MyInquiryListView,
    MyInquiryMarkReadView,
    MyListingDetailView,
    MyListingListCreateView,
    MyMarketplaceAnalyticsView,
    ParseListingGeometryView,
    PublicListingDetailView,
    PublicListingDocumentSummarizeView,
    PublicListingEventCreateView,
    PublicListingGeoJsonView,
    PublicListingListView,
)

urlpatterns = [
    path("listings/", PublicListingListView.as_view(), name="marketplace-listings"),
    path("listings/geojson/", PublicListingGeoJsonView.as_view(), name="marketplace-geojson"),
    path("listings/<slug:slug>/", PublicListingDetailView.as_view(), name="marketplace-listing-detail"),
    path(
        "listings/<slug:slug>/events/",
        PublicListingEventCreateView.as_view(),
        name="marketplace-listing-events",
    ),
    path(
        "listings/<slug:slug>/documents/<int:doc_id>/summarize/",
        PublicListingDocumentSummarizeView.as_view(),
        name="marketplace-listing-document-summarize",
    ),
    path(
        "listings/<slug:slug>/inquiries/",
        ListingInquiryCreateView.as_view(),
        name="marketplace-listing-inquiry",
    ),
    path("parse-geometry/", ParseListingGeometryView.as_view(), name="marketplace-parse-geometry"),
    path("my/analytics/", MyMarketplaceAnalyticsView.as_view(), name="marketplace-my-analytics"),
    path("my/listings/", MyListingListCreateView.as_view(), name="marketplace-my-listings"),
    path("my/listings/<int:pk>/", MyListingDetailView.as_view(), name="marketplace-my-listing-detail"),
    path(
        "my/listings/<int:pk>/documents/",
        ListingDocumentCreateView.as_view(),
        name="marketplace-my-listing-documents",
    ),
    path(
        "my/listings/<int:pk>/documents/<int:doc_id>/",
        ListingDocumentDeleteView.as_view(),
        name="marketplace-my-listing-document-delete",
    ),
    path("my/inquiries/", MyInquiryListView.as_view(), name="marketplace-my-inquiries"),
    path(
        "my/inquiries/<int:pk>/read/",
        MyInquiryMarkReadView.as_view(),
        name="marketplace-my-inquiry-read",
    ),
]
