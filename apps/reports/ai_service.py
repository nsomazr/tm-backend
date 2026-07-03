"""Multi-provider AI summary generation: Ollama, Groq, or Gemini."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a geological analyst for Terra Meta. "
    "Write concise, accessible mineral prospectivity summaries for researchers and investors."
)

MAP_INSIGHT_PROMPT = (
    "You are a geological analyst for Terra Meta, a mineral intelligence platform for Tanzania. "
    "You ONLY use the mapped data provided in the context (exact click location). "
    "Write 3-5 short bullet points about the proven mineral zones at that point. "
    "If no minerals are listed, say mapping is not available for that location. "
    "Do not describe nearby regions or guess geology outside the provided data."
)


def generate_map_insight(context: str) -> tuple[str, str]:
    """Generate location-based map insights. Returns (insight_text, model_used)."""
    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_map_provider(provider, context)
            if text and text.strip():
                return text.strip(), _model_label(provider)
        except Exception as exc:
            logger.warning("AI map insight provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    region_line = _fallback_region_line(context)
    if errors:
        return (
            f"{region_line} AI insights unavailable ({'; '.join(errors[:2])}).",
            "fallback",
        )
    return (
        f"{region_line} Configure AI keys for enhanced geological insights.",
        "fallback",
    )


def generate_summary(context: str) -> tuple[str, str]:
    """
    Try providers in order (primary + fallbacks). Returns (summary_text, model_used).
    """
    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_provider(provider, context)
            if text and text.strip():
                model_label = _model_label(provider)
                return text.strip(), model_label
        except Exception as exc:
            logger.warning("AI provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    mineral_line = _fallback_mineral_line(context)
    if errors:
        return (
            f"{mineral_line} AI summary unavailable ({'; '.join(errors[:2])}).",
            "fallback",
        )
    return (
        f"{mineral_line} Configure AI_PROVIDER and API keys in .env for generated summaries.",
        "fallback",
    )


def _provider_chain() -> list[str]:
    primary = getattr(settings, "AI_PROVIDER", "groq").lower()
    fallbacks = getattr(settings, "AI_PROVIDER_FALLBACK", "groq,gemini,ollama")
    if isinstance(fallbacks, str):
        fallback_list = [p.strip().lower() for p in fallbacks.split(",") if p.strip()]
    else:
        fallback_list = list(fallbacks)

    chain = []
    for p in [primary] + fallback_list:
        if p not in chain and _provider_configured(p):
            chain.append(p)
    return chain


def _provider_configured(provider: str) -> bool:
    if provider == "ollama":
        return bool(getattr(settings, "OLLAMA_BASE_URL", ""))
    if provider == "groq":
        return bool(getattr(settings, "GROQ_API_KEY", ""))
    if provider == "gemini":
        return bool(getattr(settings, "GEMINI_API_KEY", ""))
    return False


def _model_label(provider: str) -> str:
    labels = {
        "ollama": f"ollama/{settings.OLLAMA_MODEL}",
        "groq": f"groq/{settings.GROQ_MODEL}",
        "gemini": f"gemini/{settings.GEMINI_MODEL}",
    }
    return labels.get(provider, provider)


def _call_provider(provider: str, context: str) -> str:
    if provider == "ollama":
        return _ollama(context)
    if provider == "groq":
        return _groq(context)
    if provider == "gemini":
        return _gemini(context)
    raise ValueError(f"Unknown AI provider: {provider}")


def _call_map_provider(provider: str, context: str) -> str:
    user_msg = f"Analyze this map area in Tanzania:\n\n{context}"
    if provider == "ollama":
        return _ollama_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "groq":
        return _groq_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "gemini":
        return _gemini_custom(user_msg, MAP_INSIGHT_PROMPT)
    raise ValueError(f"Unknown AI provider: {provider}")


def _ollama(context: str) -> str:
    return _ollama_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _groq(context: str) -> str:
    return _groq_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _gemini(context: str) -> str:
    return _gemini_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _ollama_custom(user_content: str, system_prompt: str) -> str:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
    }
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["message"]["content"]


def _groq_custom(user_content: str, system_prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 600,
        "temperature": 0.4,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _gemini_custom(user_content: str, system_prompt: str) -> str:
    model = settings.GEMINI_MODEL
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.GEMINI_API_KEY}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\n{user_content}"}
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 600, "temperature": 0.4},
    }
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _fallback_region_line(context: str) -> str:
    try:
        region = context.split("Primary region:")[1].split("\n")[0].strip()
        return f"This area is in {region}, Tanzania."
    except (IndexError, AttributeError):
        return "This area is in Tanzania."


def _fallback_mineral_line(context: str) -> str:
    try:
        mineral = context.split("Mineral:")[1].split("\n")[0].strip()
        return f"This report covers {mineral} prospectivity in Tanzania."
    except (IndexError, AttributeError):
        return "This report covers mineral prospectivity in Tanzania."
