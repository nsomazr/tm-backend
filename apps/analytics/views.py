from django.db.models import Count, Q
from django.http import FileResponse
from django.utils import timezone
import io
from apps.accounts.throttling import (
    AIChatThrottleMixin,
    AIInsightThrottleMixin,
    HeatmapThrottleMixin,
    PublicCatalogThrottleMixin,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminUser
from apps.maps.access import (
    user_has_map_detail_access,
)
from apps.maps.localization import get_request_locale, localized_name
from apps.minerals.models import Mineral
from apps.analytics.credits import (
    InsufficientAssistantCredits,
    consume_assistant_credit,
    get_assistant_credit_quota,
)
from apps.analytics.models import AssistantCreditUsage
from apps.reports.ai_service import generate_assistant_chat, generate_map_insight

from .conversation import is_lightweight_user_message, platform_filler_reply
from .chat_history import (
    build_thread_key,
    get_thread_messages,
    save_thread_messages,
    user_has_chat_history,
)
from .insights import (
    area_location_context,
    build_area_ai_context,
    build_platform_ai_context,
    build_search_ai_context,
    catalog_mineral_coverage_context,
    enrich_area_insight_context,
    generate_basic_map_insight,
    generate_basic_search_insight,
    generate_unmapped_insight,
    _insight_contradicts_mapped_data,
    mineral_coverage_context,
    mineral_search_insights,
    parse_exploration_geometry,
    region_coverage_context,
    layer_coverage_context,
    admin_boundary_coverage_context,
)
from apps.reports.ai_service import generate_geological_map_insight
from .basemap_metadata import is_terrain_visual_basemap
from .similar_areas import find_similar_areas
from .insight_export import _decode_map_snapshot, build_insight_export_for_user

from .aerial import included_aerial_km2, user_can_access_aerial_analysis
from .admin_stats import build_admin_platform_analytics
from .coverage_stats import (
    ANALYTICS_LAYER_TYPES,
    analytics_features_qs,
    analytics_layers_qs,
    build_feature_coverage_stats,
    build_layer_inventory,
)
from .mineral_coverage import (
    build_layers_boundary_coverage,
    build_mineral_boundary_coverage,
    build_mineral_catalog,
    mineral_catalog_stats,
)
from .mineral_exploration import (
    MineralExplorationLimitExceeded,
    can_explore_mineral,
    ensure_mineral_exploration_allowed,
    get_mineral_exploration_quota,
)

REPORT_EXPORT_CREDITS = 5


def _area_insight_param(request, key: str, default=None):
    if request.method == "POST" and isinstance(getattr(request, "data", None), dict):
        if key in request.data:
            return request.data.get(key, default)
    alt = key.replace("_", "-") if "_" in key else key
    if request.method == "POST" and isinstance(getattr(request, "data", None), dict):
        if alt in request.data:
            return request.data.get(alt, default)
    return request.query_params.get(key, request.query_params.get(alt, default))


def _build_area_insights_response(request):
    try:
        lat = float(_area_insight_param(request, "lat", ""))
        lng = float(_area_insight_param(request, "lng", ""))
    except (TypeError, ValueError):
        return Response({"detail": "lat and lng are required."}, status=400)

    try:
        zoom = int(_area_insight_param(request, "zoom", 8))
    except (TypeError, ValueError):
        zoom = 8

    feature_ids: list[int] = []
    raw_ids = _area_insight_param(request, "feature_ids", "")
    if isinstance(raw_ids, list):
        for part in raw_ids:
            try:
                feature_ids.append(int(part))
            except (TypeError, ValueError):
                continue
    elif raw_ids:
        for part in str(raw_ids).split(","):
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
    access = user_can_access_aerial_analysis(user, lat, lng, zoom)
    analysis_km2 = access.get("analysis_area_km2", included_aerial_km2())
    country_code = _area_insight_param(request, "country", "TZ")
    basemap = _area_insight_param(request, "basemap")
    map_snapshot_raw = _area_insight_param(request, "map_snapshot")
    boundary_id = None
    raw_boundary = _area_insight_param(request, "boundary_id") or _area_insight_param(
        request, "admin_boundary_id", ""
    )
    if raw_boundary:
        try:
            boundary_id = int(raw_boundary)
        except ValueError:
            pass
    exploration_geometry = parse_exploration_geometry(
        _area_insight_param(request, "exploration_geometry")
    )
    visible_layer_ids: list[int] = []
    raw_visible = _area_insight_param(request, "visible_layer_ids", "")
    if isinstance(raw_visible, list):
        for part in raw_visible:
            try:
                visible_layer_ids.append(int(part))
            except (TypeError, ValueError):
                continue
    elif raw_visible:
        for part in str(raw_visible).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                visible_layer_ids.append(int(part))
            except ValueError:
                continue
    ctx = area_location_context(
        lat,
        lng,
        zoom,
        user,
        locale=locale,
        feature_ids=feature_ids or None,
        analysis_area_km2=analysis_km2,
        admin_boundary_id=boundary_id if not exploration_geometry else None,
        exploration_geometry=exploration_geometry,
        country_code=country_code,
        visible_layer_ids=visible_layer_ids or None,
    )
    enrich_area_insight_context(ctx, basemap=basemap, locale=locale)

    image_b64 = None
    if (
        map_snapshot_raw
        and isinstance(map_snapshot_raw, str)
        and is_terrain_visual_basemap(basemap)
    ):
        snapshot_bytes = _decode_map_snapshot(map_snapshot_raw)
        if snapshot_bytes:
            import base64

            image_b64 = base64.b64encode(snapshot_bytes).decode("ascii")

    payload = {
        **ctx,
        "ai_insight": None,
        "ai_model": None,
        "insight_tier": "none",
        "requires_subscription": False,
        "has_detail_access": has_detail,
        "assistant_credits": get_assistant_credit_quota(request, user),
        "aerial": access,
        "visual_observations": None,
        "similar_areas": [],
    }

    if ctx.get("has_mapped_data"):
        payload["similar_areas"] = find_similar_areas(ctx, user, locale=locale)

    if not has_detail:
        payload["requires_subscription"] = True
        payload["upgrade_message"] = (
            "Subscribe to unlock location Terra insights, analytics, and report downloads."
        )
        if not ctx["has_mapped_data"]:
            payload["ai_insight"] = None
        return Response(payload)

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
            payload["upgrade_message"] = "No Ask Terra credits remaining. Upgrade for more credits."
            return Response(payload)

        ai_context = build_area_ai_context(ctx)
        insight, model = generate_geological_map_insight(ai_context, image_b64=image_b64)
        if (
            model == "fallback"
            or len((insight or "").strip()) < 200
            or _insight_contradicts_mapped_data(insight, ctx)
        ):
            insight = generate_basic_map_insight(ctx, locale=locale)
            model = "template"
        payload["ai_insight"] = insight
        payload["ai_model"] = model
        if image_b64 and model != "template":
            payload["visual_observations"] = (
                f"Visual interpretation from {ctx.get('basemap_label') or 'map'} view ({model})."
            )
        payload["insight_tier"] = "full" if has_detail else "highlight"
        payload["assistant_credits"] = get_assistant_credit_quota(request, user)
    else:
        payload["ai_insight"] = generate_unmapped_insight(lat, lng, locale=locale)
        payload["insight_tier"] = "none"

    return Response(payload)


class HotspotAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (user.has_paid_access or user.is_mineral_manager or user.is_admin_user):
            return Response({"detail": "Subscription required."}, status=403)

        mineral_slug = request.query_params.get("mineral")
        qs = analytics_features_qs()

        if mineral_slug:
            qs = qs.filter(layer__mineral__slug=mineral_slug)

        locale = get_request_locale(request)
        country_code = (request.query_params.get("country") or "TZ").upper()
        coverage = build_feature_coverage_stats(qs, country_code=country_code, locale=locale)

        layer_stats = (
            analytics_layers_qs()
            .values("layer_type")
            .annotate(count=Count("id"))
        )

        return Response({
            "hotspots": coverage["hotspots"],
            "layer_hotspots": coverage["layer_hotspots"],
            "mineral_hotspots": coverage["mineral_hotspots"],
            "layers": coverage["layers"],
            "minerals": coverage["minerals"],
            "total_prospects": coverage["total_prospects"],
            "layer_stats": list(layer_stats),
            **(
                {"total_area_km2": coverage["total_area_km2"]}
                if coverage.get("total_area_km2")
                else {}
            ),
        })


class InvestorDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (user.has_paid_access or user.is_mineral_manager or user.is_admin_user):
            return Response({"detail": "Subscription required."}, status=403)

        locale = get_request_locale(request)
        mineral_layer_filter = Q(
            layers__is_active=True,
            layers__layer_type__in=ANALYTICS_LAYER_TYPES,
            layers__features__is_active=True,
        )
        minerals = Mineral.objects.filter(is_active=True).annotate(
            layer_count=Count("layers", filter=mineral_layer_filter, distinct=True),
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
        return Response({
            "minerals": data,
            "layers": build_layer_inventory(locale=locale),
        })


class MineralSearchInsightsView(AIInsightThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        query = request.query_params.get("q", "")
        results = mineral_search_insights(query, request.user)
        return Response({"results": results})


class MineralCatalogView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        locale = get_request_locale(request)
        country_code = (request.query_params.get("country") or "TZ").upper()
        minerals = build_mineral_catalog(country_code=country_code, user=request.user, locale=locale)
        stats = mineral_catalog_stats(country_code=country_code)
        return Response({"minerals": minerals, "country": country_code, "stats": stats})


class MineralBoundaryCoverageView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug: str):
        try:
            quota = ensure_mineral_exploration_allowed(request, slug)
        except MineralExplorationLimitExceeded as exc:
            return Response(
                {"detail": str(exc), "quota": exc.quota, "mineral_slug": exc.slug},
                status=403,
            )
        country_code = (request.query_params.get("country") or "TZ").upper()
        include_villages = request.query_params.get("include_villages", "").lower() in ("1", "true", "yes")
        if request.user.is_authenticated and getattr(request.user, "has_paid_access", False):
            include_villages = include_villages or request.query_params.get("include_villages") != "false"
        payload = build_mineral_boundary_coverage(
            slug,
            country_code=country_code,
            user=request.user,
            include_villages=include_villages,
        )
        if not payload:
            return Response({"detail": "Mineral not found."}, status=404)
        payload["exploration_quota"] = quota
        return Response(payload)


class LayerBoundaryCoverageView(PublicCatalogThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        country_code = (request.query_params.get("country") or "TZ").upper()
        include_villages = request.query_params.get("include_villages", "").lower() in ("1", "true", "yes")
        raw_ids = (request.query_params.get("layer_ids") or "").strip()
        layer_ids: list[int] = []
        for part in raw_ids.split(","):
            part = part.strip()
            if part.isdigit():
                layer_ids.append(int(part))
        if not layer_ids:
            return Response({"detail": "layer_ids is required."}, status=400)
        payload = build_layers_boundary_coverage(
            layer_ids,
            country_code=country_code,
            user=request.user,
            include_villages=include_villages,
        )
        return Response(payload)


class MineralHeatmapView(HeatmapThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug: str):
        from .mineral_heatmap import build_mineral_heatmap
        from .mineral_exploration import get_mineral_exploration_quota, user_can_view_mineral_heatmap

        quota = get_mineral_exploration_quota(request, request.user)
        if slug == "general":
            return Response({"detail": "Heatmap is only available for mapped commodity layers."}, status=404)
        if not user_can_view_mineral_heatmap(request.user, quota, slug):
            return Response(
                {
                    "detail": "Mineral exploration limit reached for your plan.",
                    "quota": quota,
                    "mineral_slug": slug,
                },
                status=403,
            )
        country_code = (request.query_params.get("country") or "TZ").upper()
        locale = get_request_locale(request)
        raw_layer_ids = (request.query_params.get("layer_ids") or "").strip()
        layer_ids: list[int] | None = None
        if raw_layer_ids:
            layer_ids = []
            for part in raw_layer_ids.split(","):
                part = part.strip()
                if part.isdigit():
                    layer_ids.append(int(part))
            if not layer_ids:
                layer_ids = None
        payload = build_mineral_heatmap(
            slug,
            country_code=country_code,
            user=request.user,
            layer_ids=layer_ids,
            locale=locale,
        )
        if not payload:
            return Response(
                {
                    "detail": "No heatmap for the selected layer(s).",
                    "layer_ids": layer_ids,
                    "mineral_slug": slug,
                },
                status=404,
            )
        payload["exploration_quota"] = quota
        return Response(payload)


class MineralExplorationQuotaView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(get_mineral_exploration_quota(request, request.user))


class SearchContextInsightsView(AIInsightThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        mineral_slug = (request.query_params.get("mineral_slug") or "").strip()
        region_raw = (request.query_params.get("region_id") or "").strip()
        layer_raw = (request.query_params.get("layer_id") or "").strip()
        boundary_raw = (
            (request.query_params.get("boundary_id") or request.query_params.get("admin_boundary_id") or "")
            .strip()
        )
        user = request.user
        locale = get_request_locale(request)

        ctx = None
        if mineral_slug:
            ctx = catalog_mineral_coverage_context(mineral_slug, user, locale=locale)
        elif boundary_raw:
            try:
                ctx = admin_boundary_coverage_context(int(boundary_raw), user, locale=locale)
            except (TypeError, ValueError):
                return Response({"detail": "boundary_id must be an integer."}, status=400)
        elif region_raw:
            try:
                ctx = region_coverage_context(int(region_raw), user, locale=locale)
            except (TypeError, ValueError):
                return Response({"detail": "region_id must be an integer."}, status=400)
        elif layer_raw:
            try:
                ctx = layer_coverage_context(int(layer_raw), user, locale=locale)
            except (TypeError, ValueError):
                return Response({"detail": "layer_id must be an integer."}, status=400)
        else:
            return Response(
                {"detail": "mineral_slug, region_id, layer_id, or boundary_id is required."},
                status=400,
            )

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

        if ctx["has_mapped_data"] and has_detail:
            try:
                consume_assistant_credit(
                    request,
                    kind=AssistantCreditUsage.Kind.MAP_INSIGHT,
                    user=user,
                )
            except InsufficientAssistantCredits as exc:
                payload["assistant_credits"] = exc.quota
                payload["requires_subscription"] = exc.quota.get("tier") in ("free", "anonymous")
                payload["upgrade_message"] = "No Ask Terra credits remaining. Upgrade for more credits."
                payload["ai_insight"] = generate_basic_search_insight(ctx, locale=locale)
                payload["insight_tier"] = "basic"
                return Response(payload)

            ai_context = build_search_ai_context(ctx)
            insight, model = generate_map_insight(ai_context)
            payload["ai_insight"] = insight
            payload["ai_model"] = model
            payload["insight_tier"] = "full"
            payload["assistant_credits"] = get_assistant_credit_quota(request, user)
        elif ctx["has_mapped_data"]:
            payload["requires_subscription"] = True
            payload["upgrade_message"] = (
                "Subscribe for deeper Terra insights, full analytics, and report downloads."
            )
            payload["ai_insight"] = generate_basic_search_insight(ctx, locale=locale)
            payload["insight_tier"] = "basic"
        else:
            payload["ai_insight"] = generate_basic_search_insight(ctx, locale=locale)
            payload["insight_tier"] = "none"

        return Response(payload)


class AreaInsightsView(AIInsightThrottleMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return _build_area_insights_response(request)

    def post(self, request):
        return _build_area_insights_response(request)


class AssistantCreditsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"assistant_credits": get_assistant_credit_quota(request)})


class AssistantChatHistoryView(APIView):
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


class TerraAssistantChatView(AIChatThrottleMixin, APIView):
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
        has_detail = user_has_map_detail_access(user)
        locale = get_request_locale(request)
        mode = request.data.get("mode") or "account"
        platform_only = not has_detail

        if platform_only:
            mode = "account"

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

        if platform_only:
            context = build_platform_ai_context(locale)
        elif mode == "map":
            mineral_slug = (request.data.get("mineral_slug") or "").strip()
            layer_raw = request.data.get("layer_id")
            region_raw = request.data.get("region_id")
            locale = get_request_locale(request)

            ctx = None
            if layer_raw not in (None, ""):
                try:
                    ctx = layer_coverage_context(int(layer_raw), user, locale=locale)
                except (TypeError, ValueError):
                    ctx = None
            elif mineral_slug:
                ctx = mineral_coverage_context(mineral_slug, user, locale=locale)
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

                visible_layer_ids: list[int] = []
                raw_visible = request.data.get("visible_layer_ids") or []
                if isinstance(raw_visible, list):
                    for raw in raw_visible:
                        try:
                            visible_layer_ids.append(int(raw))
                        except (TypeError, ValueError):
                            continue
                elif isinstance(raw_visible, str) and raw_visible.strip():
                    for part in raw_visible.split(","):
                        part = part.strip()
                        if not part:
                            continue
                        try:
                            visible_layer_ids.append(int(part))
                        except ValueError:
                            continue

                boundary_id = None
                raw_boundary = request.data.get("boundary_id") or request.data.get("admin_boundary_id")
                if raw_boundary not in (None, ""):
                    try:
                        boundary_id = int(raw_boundary)
                    except (TypeError, ValueError):
                        pass
                country_code = (request.data.get("country") or "TZ").upper()
                basemap = (request.data.get("basemap") or "").strip() or None
                exploration_geometry = parse_exploration_geometry(
                    request.data.get("exploration_geometry")
                )
                access = user_can_access_aerial_analysis(user, lat, lng, zoom)
                analysis_km2 = access.get("analysis_area_km2", included_aerial_km2())

                ctx = area_location_context(
                    lat,
                    lng,
                    zoom,
                    user,
                    locale=locale,
                    feature_ids=feature_ids or None,
                    analysis_area_km2=analysis_km2,
                    admin_boundary_id=boundary_id if not exploration_geometry else None,
                    exploration_geometry=exploration_geometry,
                    country_code=country_code,
                    visible_layer_ids=visible_layer_ids or None,
                )
                enrich_area_insight_context(ctx, basemap=basemap, locale=locale)
                context = build_area_ai_context(ctx)

        if not context and not platform_only:
            minerals = Mineral.objects.filter(is_active=True).order_by("name")[:12]
            locale = get_request_locale(request)
            names = ", ".join(localized_name(m, locale) for m in minerals)
            context = (
                "Terra Meta platform overview.\n"
                f"Active minerals on the map: {names or 'none listed'}.\n"
                "Users can explore the interactive map, read reports, and subscribe for full analytics."
            )

        chat_messages = messages + [{"role": "user", "content": question}]
        if platform_only and is_lightweight_user_message(question):
            reply, model = platform_filler_reply(question, locale), "filler"
        else:
            reply, model = generate_assistant_chat(
                chat_messages,
                context,
                platform_only=platform_only,
            )

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


class TerraInsightExportView(APIView):
    """Generate a 3–5 page PDF brief from selected Terra insights (paid subscribers)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user_has_map_detail_access(user):
            return Response(
                {
                    "detail": "Subscribe to export Terra insight reports.",
                    "requires_subscription": True,
                },
                status=403,
            )

        quota = get_assistant_credit_quota(request, user)
        if not quota.get("unlimited") and (quota.get("remaining") or 0) < REPORT_EXPORT_CREDITS:
            return Response(
                {
                    "detail": f"Export requires {REPORT_EXPORT_CREDITS} Ask Terra credits.",
                    "assistant_credits": quota,
                    "requires_subscription": quota.get("tier") in ("free", "anonymous"),
                },
                status=403,
            )

        mode = (request.data.get("mode") or "account").strip()
        locale = get_request_locale(request)
        raw_sections = request.data.get("sections") or []
        sections = [str(s) for s in raw_sections] if isinstance(raw_sections, list) else []

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

        mineral_slug = (request.data.get("mineral_slug") or "").strip()
        country_code = (request.data.get("country") or "TZ").upper()
        map_snapshot = request.data.get("map_snapshot")

        region_id = layer_id = boundary_id = None
        lat = lng = None
        zoom = 8
        feature_ids: list[int] = []

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

            raw_ids = request.data.get("feature_ids") or []
            if isinstance(raw_ids, list):
                for raw in raw_ids:
                    try:
                        feature_ids.append(int(raw))
                    except (TypeError, ValueError):
                        continue

            for key in ("region_id", "layer_id", "boundary_id"):
                raw = request.data.get(key) if key != "boundary_id" else (
                    request.data.get("boundary_id") or request.data.get("admin_boundary_id")
                )
                if raw in (None, ""):
                    continue
                try:
                    val = int(raw)
                except (TypeError, ValueError):
                    continue
                if key == "region_id":
                    region_id = val
                elif key == "layer_id":
                    layer_id = val
                else:
                    boundary_id = val

        exploration_geometry = parse_exploration_geometry(
            request.data.get("exploration_geometry")
        )
        analysis_km2 = None
        raw_km2 = request.data.get("analysis_area_km2")
        if raw_km2 not in (None, ""):
            try:
                analysis_km2 = float(raw_km2)
            except (TypeError, ValueError):
                analysis_km2 = None
        if analysis_km2 is None and mode == "map" and lat is not None and lng is not None:
            access = user_can_access_aerial_analysis(user, lat, lng, zoom or 8)
            analysis_km2 = access.get("analysis_area_km2")

        try:
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.REPORT_EXPORT,
                user=user,
                credits=REPORT_EXPORT_CREDITS,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {
                    "detail": f"Export requires {REPORT_EXPORT_CREDITS} Ask Terra credits.",
                    "assistant_credits": exc.quota,
                },
                status=403,
            )

        try:
            pdf_bytes = build_insight_export_for_user(
                user,
                mode=mode,
                locale=locale,
                sections=sections,
                messages=messages,
                map_snapshot_b64=map_snapshot if isinstance(map_snapshot, str) else None,
                country_code=country_code,
                lat=lat,
                lng=lng,
                zoom=zoom or 8,
                mineral_slug=mineral_slug,
                region_id=region_id,
                layer_id=layer_id,
                feature_ids=feature_ids or None,
                boundary_id=boundary_id if not exploration_geometry else None,
                exploration_geometry=exploration_geometry,
                analysis_area_km2=analysis_km2,
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        except Exception as exc:
            return Response({"detail": f"Report export failed: {exc}"}, status=500)

        filename = f"terra-insight-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        return FileResponse(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            filename=filename,
            content_type="application/pdf",
        )


class AdminPlatformAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        import logging

        logger = logging.getLogger(__name__)
        try:
            return Response(build_admin_platform_analytics())
        except Exception:
            logger.exception("Failed to build admin platform analytics")
            return Response(
                {"detail": "Could not build platform analytics. Check server logs for details."},
                status=500,
            )


class AdminManagerPerformanceView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        import logging

        from .manager_performance import build_manager_performance_review

        logger = logging.getLogger(__name__)
        try:
            return Response(build_manager_performance_review())
        except Exception:
            logger.exception("Failed to build manager performance review")
            return Response(
                {"detail": "Could not build manager performance review. Check server logs for details."},
                status=500,
            )


class AdminUserActivityAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        import logging

        from .user_activity_stats import build_admin_user_activity_analytics

        logger = logging.getLogger(__name__)
        try:
            return Response(build_admin_user_activity_analytics())
        except Exception:
            logger.exception("Failed to build user activity analytics")
            return Response(
                {"detail": "Could not build user activity analytics. Check server logs for details."},
                status=500,
            )


class AdminMineralAnalyticsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        import logging

        from .mineral_analytics_stats import build_admin_mineral_analytics

        logger = logging.getLogger(__name__)
        try:
            return Response(build_admin_mineral_analytics())
        except Exception:
            logger.exception("Failed to build mineral analytics")
            return Response(
                {"detail": "Could not build mineral analytics. Check server logs for details."},
                status=500,
            )


class AssistantPlatformSettingsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from .ai_settings import assistant_settings_payload

        return Response(assistant_settings_payload())

    def patch(self, request):
        from apps.compliance.views import log_audit

        from .ai_settings import assistant_settings_payload, update_assistant_settings

        ai_provider = request.data.get("ai_provider")
        ai_provider_fallback = request.data.get("ai_provider_fallback")
        if not isinstance(ai_provider, str) or not ai_provider.strip():
            return Response({"ai_provider": ["Primary provider is required."]}, status=400)
        if not isinstance(ai_provider_fallback, list):
            return Response(
                {"ai_provider_fallback": ["Expected a list of fallback providers."]},
                status=400,
            )

        try:
            payload = update_assistant_settings(
                ai_provider=ai_provider,
                ai_provider_fallback=ai_provider_fallback,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        log_audit(
            request,
            "assistant_settings_update",
            "AssistantPlatformSettings",
            1,
            {
                "ai_provider": payload["ai_provider"],
                "ai_provider_fallback": payload["ai_provider_fallback"],
            },
        )
        return Response(payload)
