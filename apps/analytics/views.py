from collections import defaultdict

from django.db.models import Count
from apps.accounts.throttling import PublicCatalogThrottleMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminUser
from apps.maps.access import user_has_map_detail_access
from apps.maps.localization import get_request_locale, localized_name
from apps.maps.models import MapFeature, MapLayer
from apps.minerals.models import Mineral
from apps.analytics.credits import (
    InsufficientAssistantCredits,
    consume_assistant_credit,
    get_assistant_credit_quota,
)
from apps.analytics.models import AssistantCreditUsage
from apps.reports.ai_service import generate_assistant_chat, generate_map_insight

from .admin_stats import build_admin_platform_analytics
from .chat_history import (
    build_thread_key,
    get_thread_messages,
    save_thread_messages,
    user_has_chat_history,
)
from .insights import (
    area_location_context,
    build_area_ai_context,
    build_search_ai_context,
    generate_basic_search_insight,
    generate_unmapped_insight,
    mineral_coverage_context,
    mineral_search_insights,
    region_coverage_context,
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


class MineralSearchInsightsView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        query = request.query_params.get("q", "")
        results = mineral_search_insights(query, request.user)
        return Response({"results": results})


class SearchContextInsightsView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        mineral_slug = (request.query_params.get("mineral_slug") or "").strip()
        region_raw = (request.query_params.get("region_id") or "").strip()
        user = request.user
        locale = get_request_locale(request)

        ctx = None
        if mineral_slug:
            ctx = mineral_coverage_context(mineral_slug, user, locale=locale)
        elif region_raw:
            try:
                ctx = region_coverage_context(int(region_raw), user, locale=locale)
            except (TypeError, ValueError):
                return Response({"detail": "region_id must be an integer."}, status=400)
        else:
            return Response({"detail": "mineral_slug or region_id is required."}, status=400)

        if not ctx:
            return Response({"detail": "Not found."}, status=404)

        has_detail = user_has_map_detail_access(user)
        payload = {
            **ctx,
            "ai_insight": None,
            "ai_model": None,
            "insight_tier": "none",
            "requires_subscription": False,
            "has_detail_access": has_detail,
            "assistant_credits": get_assistant_credit_quota(request, user),
        }

        if ctx["has_mapped_data"]:
            try:
                consume_assistant_credit(
                    request,
                    kind=AssistantCreditUsage.Kind.MAP_INSIGHT,
                    user=user,
                )
            except InsufficientAssistantCredits as exc:
                payload["assistant_credits"] = exc.quota
                payload["requires_subscription"] = exc.quota.get("tier") in ("free", "anonymous")
                payload["upgrade_message"] = "No Ask Terra credits remaining. Upgrade for more AI credits."
                payload["ai_insight"] = generate_basic_search_insight(ctx, locale=locale)
                payload["insight_tier"] = "basic"
                return Response(payload)

            ai_context = build_search_ai_context(ctx)
            insight, model = generate_map_insight(ai_context)
            payload["ai_insight"] = insight
            payload["ai_model"] = model
            payload["insight_tier"] = "full" if has_detail else "highlight"
            payload["assistant_credits"] = get_assistant_credit_quota(request, user)
        else:
            payload["ai_insight"] = generate_basic_search_insight(ctx, locale=locale)
            payload["insight_tier"] = "none"

        return Response(payload)


class AreaInsightsView(PublicCatalogThrottleMixin, APIView):
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

        feature_ids: list[int] = []
        raw_ids = request.query_params.get("feature_ids", "")
        if raw_ids:
            for part in raw_ids.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    feature_ids.append(int(part))
                except ValueError:
                    continue

        user = request.user
        has_detail = user_has_map_detail_access(user)
        locale = get_request_locale(request)
        ctx = area_location_context(
            lat,
            lng,
            zoom,
            user,
            locale=locale,
            feature_ids=feature_ids or None,
        )

        payload = {
            **ctx,
            "ai_insight": None,
            "ai_model": None,
            "insight_tier": "none",
            "requires_subscription": False,
            "has_detail_access": has_detail,
            "assistant_credits": get_assistant_credit_quota(request, user),
        }

        if ctx["has_mapped_data"]:
            try:
                consume_assistant_credit(
                    request,
                    kind=AssistantCreditUsage.Kind.MAP_INSIGHT,
                    user=user,
                )
            except InsufficientAssistantCredits as exc:
                payload["assistant_credits"] = exc.quota
                payload["requires_subscription"] = exc.quota.get("tier") in ("free", "anonymous")
                payload["upgrade_message"] = "No Ask Terra credits remaining. Upgrade for more AI credits."
                return Response(payload)

            ai_context = build_area_ai_context(ctx)
            insight, model = generate_map_insight(ai_context)
            payload["ai_insight"] = insight
            payload["ai_model"] = model
            payload["insight_tier"] = "full" if has_detail else "highlight"
            payload["assistant_credits"] = get_assistant_credit_quota(request, user)
        else:
            payload["ai_insight"] = generate_unmapped_insight(lat, lng, locale=locale)
            payload["insight_tier"] = "none"

        return Response(payload)


class AssistantCreditsView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"assistant_credits": get_assistant_credit_quota(request)})


class AssistantChatHistoryView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user
        mode = request.query_params.get("mode") or "account"
        thread_key = (request.query_params.get("thread_key") or "").strip()
        if not thread_key:
            lat = lng = None
            zoom = None
            mineral_slug = ""
            region_id = None
            try:
                if request.query_params.get("lat") not in (None, ""):
                    lat = float(request.query_params.get("lat"))
                if request.query_params.get("lng") not in (None, ""):
                    lng = float(request.query_params.get("lng"))
            except (TypeError, ValueError):
                pass
            try:
                if request.query_params.get("zoom") not in (None, ""):
                    zoom = int(request.query_params.get("zoom"))
            except (TypeError, ValueError):
                pass
            mineral_slug = (request.query_params.get("mineral_slug") or "").strip()
            raw_region = request.query_params.get("region_id")
            if raw_region not in (None, ""):
                try:
                    region_id = int(raw_region)
                except (TypeError, ValueError):
                    region_id = None
            thread_key = build_thread_key(
                mode=mode,
                lat=lat,
                lng=lng,
                zoom=zoom,
                mineral_slug=mineral_slug,
                region_id=region_id,
            )

        has_history = user_has_chat_history(user) if user.is_authenticated else False
        messages = get_thread_messages(user, thread_key) if has_history else []
        return Response(
            {
                "thread_key": thread_key,
                "chat_history": has_history,
                "messages": messages,
            }
        )


class TerraAssistantChatView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        question = (request.data.get("question") or "").strip()
        if not question:
            return Response({"detail": "question is required."}, status=400)

        raw_messages = request.data.get("messages") or []
        messages: list[dict[str, str]] = []
        if isinstance(raw_messages, list):
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = (item.get("content") or "").strip()
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        user = request.user

        try:
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.CHAT,
                user=user,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {
                    "detail": "No Ask Terra credits remaining.",
                    "assistant_credits": exc.quota,
                    "requires_subscription": exc.quota.get("tier") in ("free", "anonymous"),
                },
                status=403,
            )

        context = (request.data.get("context") or "").strip()
        mode = request.data.get("mode") or "map"

        if mode == "map":
            mineral_slug = (request.data.get("mineral_slug") or "").strip()
            region_raw = request.data.get("region_id")
            locale = get_request_locale(request)

            if mineral_slug:
                ctx = mineral_coverage_context(mineral_slug, user, locale=locale)
                if ctx:
                    context = build_search_ai_context(ctx)
            elif region_raw is not None and str(region_raw).strip():
                try:
                    ctx = region_coverage_context(int(region_raw), user, locale=locale)
                except (TypeError, ValueError):
                    ctx = None
                if ctx:
                    context = build_search_ai_context(ctx)
            elif not context:
                try:
                    lat = float(request.data.get("lat", ""))
                    lng = float(request.data.get("lng", ""))
                except (TypeError, ValueError):
                    return Response({"detail": "lat and lng are required for map mode."}, status=400)
                try:
                    zoom = int(request.data.get("zoom", 8))
                except (TypeError, ValueError):
                    zoom = 8

                feature_ids: list[int] = []
                raw_ids = request.data.get("feature_ids") or []
                if isinstance(raw_ids, list):
                    for raw in raw_ids:
                        try:
                            feature_ids.append(int(raw))
                        except (TypeError, ValueError):
                            continue

                ctx = area_location_context(
                    lat,
                    lng,
                    zoom,
                    user,
                    locale=locale,
                    feature_ids=feature_ids or None,
                )
                context = build_area_ai_context(ctx)

        if not context:
            minerals = Mineral.objects.filter(is_active=True).order_by("name")[:12]
            locale = get_request_locale(request)
            names = ", ".join(localized_name(m, locale) for m in minerals)
            context = (
                "Terra Meta platform overview.\n"
                f"Active minerals on the map: {names or 'none listed'}.\n"
                "Users can explore the interactive map, read reports, and subscribe for full analytics."
            )

        chat_messages = messages + [{"role": "user", "content": question}]
        reply, model = generate_assistant_chat(chat_messages, context)

        thread_key = (request.data.get("thread_key") or "").strip()
        if not thread_key:
            mineral_slug = (request.data.get("mineral_slug") or "").strip()
            region_raw = request.data.get("region_id")
            region_id = None
            if region_raw not in (None, ""):
                try:
                    region_id = int(region_raw)
                except (TypeError, ValueError):
                    region_id = None
            lat = lng = None
            zoom = None
            if mode == "map":
                try:
                    lat = float(request.data.get("lat", ""))
                    lng = float(request.data.get("lng", ""))
                except (TypeError, ValueError):
                    lat = lng = None
                try:
                    zoom = int(request.data.get("zoom", 8))
                except (TypeError, ValueError):
                    zoom = 8
            thread_key = build_thread_key(
                mode=mode,
                lat=lat,
                lng=lng,
                zoom=zoom,
                mineral_slug=mineral_slug,
                region_id=region_id,
            )

        if user.is_authenticated and user_has_chat_history(user):
            save_thread_messages(
                user,
                thread_key,
                messages
                + [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": reply},
                ],
            )

        return Response(
            {
                "reply": reply,
                "ai_model": model,
                "assistant_credits": get_assistant_credit_quota(request, user),
                "thread_key": thread_key,
                "chat_history": user.is_authenticated and user_has_chat_history(user),
            }
        )


class AdminPlatformAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(build_admin_platform_analytics())
