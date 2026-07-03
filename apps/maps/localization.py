"""Shared locale helpers for bilingual API responses."""


def get_request_locale(request) -> str:
    if request is None:
        return "en"
    raw = request.headers.get("Accept-Language") or request.query_params.get("lang") or "en"
    primary = raw.split(",")[0].strip().lower()[:2]
    return "sw" if primary == "sw" else "en"


def localized_name(obj, locale: str | None = None) -> str:
    name = (getattr(obj, "name", None) or "").strip()
    name_sw = (getattr(obj, "name_sw", None) or "").strip()
    if locale == "sw":
        return name_sw or name
    return name or name_sw
