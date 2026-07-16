"""JWT authentication that treats invalid tokens as anonymous on public routes."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class OptionalJWTAuthentication(JWTAuthentication):
    """Allow public endpoints to work when the client sends an expired or invalid Bearer token."""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
        except (InvalidToken, TokenError):
            return None

        return self.get_user(validated_token), validated_token


def unauthorized_if_invalid_bearer(request) -> Response | None:
    """Force 401 when a Bearer token was sent but authentication failed.

    OptionalJWTAuthentication otherwise treats bad tokens as anonymous so free
    public routes keep working. Privilege-gated AllowAny views (insights, chat)
    must not silently downgrade a logged-in admin/subscriber to the free tier —
    return 401 so the client can refresh the token and retry.
    """
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if not auth.lower().startswith("bearer "):
        return None
    if getattr(request.user, "is_authenticated", False):
        return None
    return Response(
        {"detail": "Authentication credentials expired or invalid."},
        status=401,
    )
