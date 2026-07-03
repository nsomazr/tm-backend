"""Persisted Ask Terra chat threads for paid subscribers."""

from __future__ import annotations

from apps.accounts.models import User
from apps.reports.access import _active_paid_subscription

MAX_THREAD_MESSAGES = 80


def user_has_chat_history(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_admin_user or user.role == User.Role.MINERAL_MANAGER:
        return True
    sub = _active_paid_subscription(user)
    if not sub:
        return False
    return bool(getattr(sub.plan, "includes_chat_history", False))


def build_thread_key(
    *,
    mode: str = "account",
    lat: float | None = None,
    lng: float | None = None,
    zoom: int | None = None,
    mineral_slug: str = "",
    region_id: int | None = None,
) -> str:
    if mode == "account":
        return "account"
    if mineral_slug:
        return f"search:mineral:{mineral_slug}"
    if region_id is not None:
        return f"search:region:{region_id}"
    if lat is not None and lng is not None:
        z = int(zoom or 8)
        return f"map:{round(float(lat), 3)}:{round(float(lng), 3)}:{z}"
    return "map:general"


def get_thread_messages(user, thread_key: str) -> list[dict[str, str]]:
    from .models import AssistantChatThread

    if not user_has_chat_history(user):
        return []
    thread = AssistantChatThread.objects.filter(user=user, thread_key=thread_key).first()
    if not thread or not isinstance(thread.messages, list):
        return []
    out: list[dict[str, str]] = []
    for item in thread.messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out[-MAX_THREAD_MESSAGES:]


def save_thread_messages(user, thread_key: str, messages: list[dict[str, str]]) -> None:
    from .models import AssistantChatThread

    if not user_has_chat_history(user):
        return
    cleaned: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            cleaned.append({"role": role, "content": content})
    cleaned = cleaned[-MAX_THREAD_MESSAGES:]
    AssistantChatThread.objects.update_or_create(
        user=user,
        thread_key=thread_key,
        defaults={"messages": cleaned},
    )
