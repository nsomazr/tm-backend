"""Record marketplace listing engagement events and build owner analytics."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from .models import ListingEvent, MarketplaceListing

KIND_COUNTER = {
    ListingEvent.Kind.VIEW: "view_count",
    ListingEvent.Kind.MAP_CLICK: "map_click_count",
    ListingEvent.Kind.DOCUMENT_DOWNLOAD: "document_download_count",
    ListingEvent.Kind.TERRA_SUMMARY: "terra_summary_count",
}


def record_listing_event(
    listing: MarketplaceListing,
    kind: str,
    *,
    user=None,
    session_key: str = "",
) -> ListingEvent | None:
    if kind not in ListingEvent.Kind.values:
        return None
    if listing.deleted_at is not None:
        return None

    event = ListingEvent.objects.create(
        listing=listing,
        kind=kind,
        user=user if getattr(user, "is_authenticated", False) else None,
        session_key=(session_key or "")[:64],
    )
    counter = KIND_COUNTER.get(kind)
    if counter:
        MarketplaceListing.objects.filter(pk=listing.pk).update(**{counter: F(counter) + 1})
    return event


def owner_analytics_payload(user) -> dict:
    listings = list(
        MarketplaceListing.objects.filter(owner=user, deleted_at__isnull=True)
        .annotate(
            inquiry_total=Count("inquiries", distinct=True),
            inquiry_unread=Count("inquiries", filter=Q(inquiries__is_read=False), distinct=True),
        )
        .order_by("-updated_at")
    )
    listing_ids = [item.id for item in listings]
    since = timezone.now() - timedelta(days=30)
    recent = (
        ListingEvent.objects.filter(listing_id__in=listing_ids, created_at__gte=since)
        .values("kind")
        .annotate(count=Count("id"))
    )
    recent_by_kind = {row["kind"]: int(row["count"]) for row in recent}

    totals = {
        "listings": len(listings),
        "published": sum(1 for item in listings if item.status == MarketplaceListing.Status.PUBLISHED),
        "draft": sum(1 for item in listings if item.status == MarketplaceListing.Status.DRAFT),
        "hidden": sum(1 for item in listings if item.status == MarketplaceListing.Status.HIDDEN),
        "views": sum(int(item.view_count or 0) for item in listings),
        "map_clicks": sum(int(item.map_click_count or 0) for item in listings),
        "document_downloads": sum(int(item.document_download_count or 0) for item in listings),
        "terra_summaries": sum(int(item.terra_summary_count or 0) for item in listings),
        "inquiries": sum(int(item.inquiry_total or 0) for item in listings),
        "inquiries_unread": sum(int(item.inquiry_unread or 0) for item in listings),
        "views_30d": int(recent_by_kind.get(ListingEvent.Kind.VIEW, 0)),
        "map_clicks_30d": int(recent_by_kind.get(ListingEvent.Kind.MAP_CLICK, 0)),
        "document_downloads_30d": int(recent_by_kind.get(ListingEvent.Kind.DOCUMENT_DOWNLOAD, 0)),
        "terra_summaries_30d": int(recent_by_kind.get(ListingEvent.Kind.TERRA_SUMMARY, 0)),
    }
    views = totals["views"]
    inquiries = totals["inquiries"]
    totals["inquiry_rate"] = round((inquiries / views) * 100, 1) if views else 0.0

    per_listing = []
    for item in listings:
        item_views = int(item.view_count or 0)
        item_inquiries = int(item.inquiry_total or 0)
        per_listing.append(
            {
                "id": item.id,
                "slug": item.slug,
                "title": item.title,
                "status": item.status,
                "show_on_map": item.show_on_map,
                "views": item_views,
                "map_clicks": int(item.map_click_count or 0),
                "document_downloads": int(item.document_download_count or 0),
                "terra_summaries": int(item.terra_summary_count or 0),
                "inquiries": item_inquiries,
                "inquiries_unread": int(item.inquiry_unread or 0),
                "inquiry_rate": round((item_inquiries / item_views) * 100, 1) if item_views else 0.0,
                "updated_at": item.updated_at.isoformat(),
            }
        )

    insights: list[str] = []
    if not listings:
        insights.append("Create a listing to start collecting marketplace views and inquiries.")
    else:
        published = [item for item in per_listing if item["status"] == MarketplaceListing.Status.PUBLISHED]
        if not published:
            insights.append("Publish a listing so it appears on the public Marketplace map.")
        top = max(per_listing, key=lambda row: row["views"], default=None)
        if top and top["views"] > 0:
            insights.append(f"“{top['title']}” leads with {top['views']} views.")
        cold = [
            item
            for item in published
            if item["show_on_map"] and item["views"] == 0
        ]
        if cold:
            insights.append(
                f"{len(cold)} published listing{'s' if len(cold) != 1 else ''} "
                "have no views yet — share the public link or refine title/commodities."
            )
        if totals["inquiries_unread"]:
            insights.append(f"You have {totals['inquiries_unread']} unread inquir{'y' if totals['inquiries_unread'] == 1 else 'ies'}.")
        if views and inquiries == 0:
            insights.append(
                "Listings are getting views but no inquiries yet — check contact settings and listing description."
            )
        if totals["terra_summaries_30d"]:
            insights.append(
                f"Buyers used Terra summary {totals['terra_summaries_30d']} time"
                f"{'' if totals['terra_summaries_30d'] == 1 else 's'} in the last 30 days."
            )
        if not insights:
            insights.append("Marketplace activity looks steady. Keep listings updated as new data arrives.")

    return {
        "totals": totals,
        "listings": per_listing,
        "insights": insights,
    }
