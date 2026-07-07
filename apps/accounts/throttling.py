from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle


class AuthAnonThrottle(AnonRateThrottle):
    scope = "auth"


class OTPSendThrottle(SimpleRateThrottle):
    scope = "otp_send"

    def get_cache_key(self, request, view):
        email = ""
        if isinstance(request.data, dict):
            email = str(request.data.get("email", "")).strip().lower()
        ident = self.get_ident(request)
        if email:
            return f"otp_send_{ident}_{email}"
        return f"otp_send_{ident}"


class OTPVerifyThrottle(SimpleRateThrottle):
    scope = "otp_verify"

    def get_cache_key(self, request, view):
        email = ""
        if isinstance(request.data, dict):
            email = str(request.data.get("email", "")).strip().lower()
        ident = self.get_ident(request)
        if email:
            return f"otp_verify_{ident}_{email}"
        return f"otp_verify_{ident}"


class AdminUploadThrottle(SimpleRateThrottle):
    scope = "upload"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"upload_user_{request.user.pk}"
        return f"upload_{self.get_ident(request)}"


class MapGeojsonAnonThrottle(AnonRateThrottle):
    """Rate-limit anonymous bulk fetching of map geometry (scraping defence).

    AnonRateThrottle only applies to unauthenticated requests, so paying/logged-in
    users are unaffected.
    """

    scope = "map_geojson"


class PublicCatalogThrottleMixin:
    """Read-only catalog endpoints should not share the global anon burst budget."""

    throttle_classes = []


class AIAnonRateThrottle(AnonRateThrottle):
    scope = "ai_anon"


class AIUserRateThrottle(UserRateThrottle):
    scope = "ai_user"


class AIChatAnonRateThrottle(AnonRateThrottle):
    scope = "ai_chat_anon"


class AIChatUserRateThrottle(UserRateThrottle):
    scope = "ai_chat_user"


class HeatmapAnonRateThrottle(AnonRateThrottle):
    scope = "heatmap_anon"


class AIInsightThrottleMixin:
    throttle_classes = [AIAnonRateThrottle, AIUserRateThrottle]


class AIChatThrottleMixin:
    throttle_classes = [AIChatAnonRateThrottle, AIChatUserRateThrottle]


class HeatmapThrottleMixin:
    throttle_classes = [HeatmapAnonRateThrottle, AIUserRateThrottle]
