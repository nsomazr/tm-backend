from collections import defaultdict

from django.db.models import Count
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminUser
from apps.maps.access import user_has_map_detail_access
from apps.maps.localization import get_request_locale, localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral
from apps.reports.ai_service import generate_map_insight

from .admin_stats import build_admin_platform_analytics
from .insights import (
    area_location_context,
    build_area_ai_context,
    generate_unmapped_insight,
    mineral_search_insights,
)


class HotspotAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (user.has_paid_access or user.is_mineral_manager or user.is_admin_user):
            return Response({"detail": "Subscription required."}, status=403)

        mineral_slug = request.query_params.get("mineral")
        qs = MapFeature.objects.filter(
            is_active=True,
            layer__is_active=True,
        ).select_related("layer", "layer__mineral", "layer__region")

        if mineral_slug:
            qs = qs.filter(layer__mineral__slug=mineral_slug)

        locale = get_request_locale(request)
        region_counts = defaultdict(int)
        mineral_counts = defaultdict(lambda: {"count": 0, "name": "", "name_sw": "", "color": ""})

        for feature in qs[:5000]:
            region_name = feature.layer.region.name if feature.layer.region else "Unknown"
            region_counts[region_name] += 1
            m = feature.layer.mineral
            mineral_counts[m.slug]["count"] += 1
            mineral_counts[m.slug]["name"] = localized_name(m, locale)
            mineral_counts[m.slug]["name_sw"] = m.name_sw
            mineral_counts[m.slug]["color"] = m.color

        hotspots = sorted(
            [{"region": k, "feature_count": v} for k, v in region_counts.items()],
            key=lambda x: x["feature_count"],
            reverse=True,
        )[:10]

        minerals = [
            {"slug": slug, **data}
            for slug, data in mineral_counts.items()
        ]

        layer_stats = (
            MapLayer.objects.filter(is_active=True)
            .values("layer_type")
            .annotate(count=Count("id"))
        )

        return Response({
            "hotspots": hotspots,
            "minerals": minerals,
            "layer_stats": list(layer_stats),
        })


class InvestorDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (user.has_paid_access or user.is_mineral_manager or user.is_admin_user):
            return Response({"detail": "Subscription required."}, status=403)

        locale = get_request_locale(request)
        minerals = Mineral.objects.filter(is_active=True).annotate(
            layer_count=Count("layers"),
            report_count=Count("reports"),
        )
        data = [
            {
                "name": localized_name(m, locale),
                "name_sw": m.name_sw,
                "slug": m.slug,
                "color": m.color,
                "layer_count": m.layer_count,
                "report_count": m.report_count,
            }
            for m in minerals
        ]
        return Response({"minerals": data})


class MineralSearchInsightsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        query = request.query_params.get("q", "")
        results = mineral_search_insights(query, request.user)
        return Response({"results": results})


class AreaInsightsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            lat = float(request.query_params.get("lat", ""))
            lng = float(request.query_params.get("lng", ""))
        except (TypeError, ValueError):
            return Response({"detail": "lat and lng are required."}, status=400)

        try:
            zoom = int(request.query_params.get("zoom", 8))
        except (TypeError, ValueError):
            zoom = 8

        user = request.user
        has_detail = user_has_map_detail_access(user)
        locale = get_request_locale(request)
        ctx = area_location_context(lat, lng, zoom, user, locale=locale)

        payload = {
            **ctx,
            "ai_insight": None,
            "ai_model": None,
            "insight_tier": "none",
            "requires_subscription": False,
            "has_detail_access": has_detail,
        }

        if ctx["has_mapped_data"]:
            ai_context = build_area_ai_context(ctx)
            insight, model = generate_map_insight(ai_context)
            payload["ai_insight"] = insight
            payload["ai_model"] = model
            payload["insight_tier"] = "full" if has_detail else "highlight"
        else:
            payload["ai_insight"] = generate_unmapped_insight(lat, lng, locale=locale)
            payload["insight_tier"] = "none"

        return Response(payload)


class AdminPlatformAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(build_admin_platform_analytics())
