"""Runtime assistant provider selection (DB overrides with env fallback)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

VALID_AI_PROVIDERS = ("groq", "gemini", "ollama")
CHAT_CAPABILITIES = frozenset({"completion", "tools", "thinking", "vision"})


def _normalize_provider(value: str) -> str:
    return (value or "").strip().lower()


def parse_provider_csv(value: str) -> list[str]:
    providers: list[str] = []
    for part in (value or "").split(","):
        provider = _normalize_provider(part)
        if provider in VALID_AI_PROVIDERS and provider not in providers:
            providers.append(provider)
    return providers


def get_assistant_platform_settings():
    from .models import AssistantPlatformSettings

    return AssistantPlatformSettings.get_solo()


def effective_ai_provider_config() -> tuple[str, list[str]]:
    solo = get_assistant_platform_settings()
    primary = _normalize_provider(solo.ai_provider) or _normalize_provider(getattr(settings, "AI_PROVIDER", "groq"))
    if primary not in VALID_AI_PROVIDERS:
        primary = "groq"

    if solo.ai_provider_fallback.strip():
        fallback_list = parse_provider_csv(solo.ai_provider_fallback)
    else:
        fallback_raw = getattr(settings, "AI_PROVIDER_FALLBACK", "gemini,ollama")
        fallback_list = parse_provider_csv(fallback_raw if isinstance(fallback_raw, str) else ",".join(fallback_raw))

    return primary, fallback_list


def _ollama_bases() -> list[str]:
    bases: list[str] = []
    primary = getattr(settings, "OLLAMA_BASE_URL", "").strip().rstrip("/")
    if primary:
        bases.append(primary)
    for candidate in ("http://127.0.0.1:11434", "http://host.docker.internal:11434"):
        if candidate not in bases:
            bases.append(candidate)
    return bases


def _ollama_active_base() -> str | None:
    for base in _ollama_bases():
        try:
            response = requests.get(f"{base}/api/tags", timeout=3)
            if response.status_code == 200:
                return base
        except Exception as exc:
            logger.debug("Ollama unreachable at %s: %s", base, exc)
    return None


def _ollama_model_entries() -> list[dict[str, Any]]:
    base = _ollama_active_base()
    if not base:
        return []
    try:
        response = requests.get(f"{base.rstrip('/')}/api/tags", timeout=3)
        if response.status_code != 200:
            return []
        payload = response.json()
        return payload.get("models") or []
    except Exception as exc:
        logger.debug("Ollama tags unavailable at %s: %s", base, exc)
        return []


def _ollama_model_is_chat_capable(entry: dict[str, Any]) -> bool:
    capabilities = entry.get("capabilities")
    if not capabilities:
        # Older Ollama builds omit capabilities; assume chat unless name looks embed-only.
        name = (entry.get("name") or "").lower()
        return "embed" not in name
    return any(cap in CHAT_CAPABILITIES for cap in capabilities)


def ollama_chat_models() -> list[str]:
    entries = [
        entry
        for entry in _ollama_model_entries()
        if _ollama_model_is_chat_capable(entry) and (entry.get("name") or "").strip()
    ]
    entries.sort(key=lambda row: row.get("modified_at") or "", reverse=True)
    names: list[str] = []
    for entry in entries:
        name = (entry.get("name") or "").strip()
        if name not in names:
            names.append(name)
    return names


VISION_MODEL_HINTS = ("llava", "bakllava", "moondream", "vision", "minicpm-v", "gemma3")


def _ollama_model_is_vision_capable(entry: dict[str, Any]) -> bool:
    capabilities = entry.get("capabilities") or []
    if "vision" in capabilities:
        return True
    name = (entry.get("name") or "").lower()
    return any(hint in name for hint in VISION_MODEL_HINTS)


def ollama_vision_models() -> list[str]:
    entries = [
        entry
        for entry in _ollama_model_entries()
        if _ollama_model_is_vision_capable(entry) and (entry.get("name") or "").strip()
    ]
    entries.sort(key=lambda row: row.get("modified_at") or "", reverse=True)
    names: list[str] = []
    for entry in entries:
        name = (entry.get("name") or "").strip()
        if name not in names:
            names.append(name)
    return names


def ollama_resolve_vision_model() -> str | None:
    configured = (getattr(settings, "OLLAMA_VISION_MODEL", "") or "").strip()
    vision_models = ollama_vision_models()
    if not vision_models:
        return None
    if configured:
        configured_base = configured.split(":")[0]
        for name in vision_models:
            if name == configured or name.split(":")[0] == configured_base:
                return name
    return vision_models[0]


def vision_provider_chain() -> list[str]:
    """Providers that can interpret map snapshots (Gemini, Ollama LLaVA, etc.)."""
    chain: list[str] = []
    if getattr(settings, "GEMINI_API_KEY", ""):
        chain.append("gemini")
    if ollama_resolve_vision_model():
        chain.append("ollama")
    return chain


def ollama_resolve_model() -> str | None:
    configured = (getattr(settings, "OLLAMA_MODEL", "") or "llama3.2").strip()
    chat_models = ollama_chat_models()
    if not chat_models:
        return None

    configured_base = configured.split(":")[0]
    for name in chat_models:
        base = name.split(":")[0]
        if name == configured or base == configured_base:
            return name

    return chat_models[0]


def ollama_reachable() -> bool:
    return ollama_resolve_model() is not None


def provider_configured(provider: str) -> bool:
    provider = _normalize_provider(provider)
    if provider == "ollama":
        return ollama_reachable()
    if provider == "groq":
        return bool(getattr(settings, "GROQ_API_KEY", ""))
    if provider == "gemini":
        return bool(getattr(settings, "GEMINI_API_KEY", ""))
    return False


def provider_chain() -> list[str]:
    primary, fallback_list = effective_ai_provider_config()
    chain: list[str] = []
    for provider in [primary, *fallback_list]:
        if provider not in chain and provider_configured(provider):
            chain.append(provider)
    # Local Ollama is always attempted last when reachable, even if not toggled in admin fallbacks.
    if "ollama" not in chain and ollama_reachable():
        chain.append("ollama")
    # Prefer local Ollama first when available — avoids cloud rate limits and long retry delays.
    if ollama_reachable():
        chain = ["ollama"] + [provider for provider in chain if provider != "ollama"]
    return chain


def provider_model_name(provider: str) -> str:
    provider = _normalize_provider(provider)
    if provider == "groq":
        return getattr(settings, "GROQ_MODEL", "")
    if provider == "gemini":
        return getattr(settings, "GEMINI_MODEL", "")
    if provider == "ollama":
        return getattr(settings, "OLLAMA_MODEL", "")
    return ""


def provider_status() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for provider in VALID_AI_PROVIDERS:
        configured = provider == "ollama" or bool(
            getattr(settings, "GROQ_API_KEY", "") if provider == "groq" else getattr(settings, "GEMINI_API_KEY", "")
        )
        available = provider_configured(provider)
        row: dict = {
            "configured": configured,
            "available": available,
            "model": provider_model_name(provider),
        }
        if provider == "ollama":
            resolved = ollama_resolve_model()
            configured = provider_model_name(provider)
            active_base = _ollama_active_base()
            row["base_url"] = active_base or getattr(settings, "OLLAMA_BASE_URL", "")
            row["model"] = resolved or configured
            row["configured_model"] = configured
            row["installed_chat_models"] = ollama_chat_models()
            row["installed_vision_models"] = ollama_vision_models()
            row["vision_model"] = ollama_resolve_vision_model()
            row["using_fallback_model"] = bool(
                resolved and configured and resolved.split(":")[0] != configured.split(":")[0]
            )
        rows[provider] = row
    return rows


def assistant_settings_payload() -> dict:
    solo = get_assistant_platform_settings()
    primary, fallback_list = effective_ai_provider_config()
    env_primary = _normalize_provider(getattr(settings, "AI_PROVIDER", "groq"))
    env_fallback = parse_provider_csv(getattr(settings, "AI_PROVIDER_FALLBACK", "gemini,ollama"))
    return {
        "ai_provider": primary,
        "ai_provider_fallback": fallback_list,
        "effective_chain": provider_chain(),
        "providers": provider_status(),
        "uses_env_defaults": not solo.ai_provider.strip() and not solo.ai_provider_fallback.strip(),
        "env_defaults": {
            "ai_provider": env_primary,
            "ai_provider_fallback": env_fallback,
        },
        "updated_at": solo.updated_at.isoformat() if solo.updated_at else None,
    }


def update_assistant_settings(*, ai_provider: str, ai_provider_fallback: list[str]) -> dict:
    primary = _normalize_provider(ai_provider)
    if primary not in VALID_AI_PROVIDERS:
        raise ValueError(f"Unknown provider: {ai_provider}")

    fallbacks: list[str] = []
    for provider in ai_provider_fallback:
        normalized = _normalize_provider(provider)
        if normalized in VALID_AI_PROVIDERS and normalized != primary and normalized not in fallbacks:
            fallbacks.append(normalized)

    solo = get_assistant_platform_settings()
    solo.ai_provider = primary
    solo.ai_provider_fallback = ",".join(fallbacks)
    solo.save(update_fields=["ai_provider", "ai_provider_fallback", "updated_at"])
    return assistant_settings_payload()
