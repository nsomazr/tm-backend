from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


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


class PublicCatalogThrottleMixin:
    """Read-only catalog endpoints should not share the global anon burst budget."""

    throttle_classes = []
