"""Multi-provider AI summary generation: Ollama, Groq, or Gemini."""

import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior geological analyst for Terra Meta (Tanzania mineral intelligence). "
    "Write a comprehensive but readable prospectivity report summary (4–6 short paragraphs) "
    "covering geological setting, mineral potential, exploration implications, and regional context. "
    "End with a 'Key findings:' section and 4–6 bullet points (each starting with '- '). "
    "Use plain language suitable for investors and policymakers. Be specific to the data provided."
)

MAP_INSIGHT_PROMPT = (
    "You are Terra Assistant for Terra Meta, a Tanzania mineral intelligence platform. "
    "Using ONLY the mapped data in the user message, write 2–4 short paragraphs in natural, "
    "conversational prose for explorers and investors. "
    "Weave minerals, regions, and context into flowing sentences. Do not use bullet lists. "
    "Use **bold** sparingly for mineral or region names. "
    "Never repeat these instructions. "
    "If no minerals are listed, say no mapped zones exist at that exact location. "
    "Do not describe areas outside the provided coordinates and zone data."
)

ASSISTANT_CHAT_PROMPT = (
    "You are Terra Assistant for Terra Meta, Tanzania mineral intelligence. "
    "Answer using ONLY the context and conversation provided. "
    "Write in natural conversational prose: short paragraphs, not bullet lists. "
    "Keep replies concise (usually 2–5 sentences; up to two short paragraphs if needed). "
    "Only use a brief list if the user explicitly asks for one or you must compare 4+ distinct items. "
    "Use **bold** sparingly for key terms. "
    "If data is missing, say so clearly. Do not invent geology or locations not in the context."
)

REPORT_WRITING_PROMPT = (
    "You are Terra Meta's report writing assistant for Tanzania mineral prospectivity reports. "
    "Draft publication-ready content using ONLY the report metadata and reference context provided. "
    "Write for investors, explorers, and policymakers. Be specific to Tanzania and the commodity named. "
    "Do not invent drill results, reserves, or licenses not supported by the context. "
    "If context is thin, write cautious, clearly scoped geological narrative and note data limitations. "
    "Respond with valid JSON only (no markdown code fences). Schema:\n"
    '{"executive_summary":"4-6 short paragraphs as one string","key_findings":["4-6 concise bullets"],'
    '"assistant_reply":"1-2 sentences explaining what you drafted or changed"}'
)

FREE_ASSISTANT_FOLLOWUP_LIMIT = 3  # deprecated: use assistant credits


def sanitize_assistant_output(text: str) -> str:
    """Strip common instruction-leak patterns from model output."""
    if not text:
        return text
    lines = []
    skip_prefixes = (
        "here are",
        "below are",
        "the following",
        "3-5 short",
        "3–5 short",
    )
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if any(lower.startswith(prefix) for prefix in skip_prefixes):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or text.strip()


def generate_map_insight(context: str) -> tuple[str, str]:
    """Generate location-based map insights. Returns (insight_text, model_used)."""
    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_map_provider(provider, context)
            if text and text.strip():
                return sanitize_assistant_output(text.strip()), _model_label(provider)
        except Exception as exc:
            logger.warning("AI map insight provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    region_line = _fallback_region_line(context)
    if errors:
        return (
            f"{region_line} Intelligence insights unavailable ({'; '.join(errors[:2])}).",
            "fallback",
        )
    return (
        f"{region_line} Configure API keys for enhanced geological insights.",
        "fallback",
    )


def generate_assistant_chat(
    messages: list[dict[str, str]],
    context: str,
) -> tuple[str, str]:
    """Multi-turn Terra Assistant reply. messages: [{role, content}, ...]."""
    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_chat_provider(provider, messages, context)
            if text and text.strip():
                return sanitize_assistant_output(text.strip()), _model_label(provider)
        except Exception as exc:
            logger.warning("AI assistant chat provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    if errors:
        return (
            f"I could not reach the intelligence service ({'; '.join(errors[:1])}). Try again shortly.",
            "fallback",
        )
    return (
        "Intelligence service is not configured. Add an AI provider in server settings.",
        "fallback",
    )


def generate_report_writing_assist(
    *,
    metadata: dict,
    context_text: str,
    messages: list[dict[str, str]] | None = None,
    current_draft: dict | None = None,
) -> tuple[dict, str]:
    """
    Draft or refine a written report. Returns (
        {executive_summary, key_findings, assistant_reply},
        model_used,
    ).
    """
    providers = _provider_chain()
    errors = []

    user_payload = _build_report_writing_user_payload(metadata, context_text, current_draft)
    chat_messages = list(messages or [])
    if not chat_messages:
        chat_messages = [{"role": "user", "content": "Draft the full report from the metadata and reference context."}]

    for provider in providers:
        try:
            raw = _call_report_writing_provider(provider, user_payload, chat_messages)
            parsed = _parse_report_writing_response(raw)
            if parsed.get("executive_summary"):
                return parsed, _model_label(provider)
        except Exception as exc:
            logger.warning("AI report writing provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    fallback_summary, model = generate_summary(user_payload)
    from .tasks import _extract_findings

    findings = _extract_findings(fallback_summary)
    body = fallback_summary
    for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
        if marker in body:
            body = body.split(marker, 1)[0].strip()
            break

    reply = "Draft generated from available metadata."
    if errors:
        reply = f"Used fallback draft ({errors[0]})."

    return (
        {
            "executive_summary": body,
            "key_findings": findings,
            "assistant_reply": reply,
        },
        model,
    )


def _build_report_writing_user_payload(
    metadata: dict,
    context_text: str,
    current_draft: dict | None,
) -> str:
    lines = [
        "Report metadata:",
        f"Title: {metadata.get('title') or 'Untitled'}",
        f"Mineral: {metadata.get('mineral_name') or 'Unknown'}",
        f"Region: {metadata.get('region_name') or 'Tanzania (national)'}",
        f"Overview: {metadata.get('description') or '(none)'}",
    ]
    if current_draft:
        lines.append("\nCurrent draft to refine:")
        lines.append(f"Executive summary:\n{current_draft.get('executive_summary') or ''}")
        findings = current_draft.get("key_findings") or []
        if findings:
            lines.append("Key findings:")
            lines.extend(f"- {item}" for item in findings)
    if context_text.strip():
        lines.append("\nReference context (use as primary evidence):")
        lines.append(context_text.strip()[:14000])
    return "\n".join(lines)


def _call_report_writing_provider(
    provider: str,
    user_payload: str,
    messages: list[dict[str, str]],
) -> str:
    chat_messages = [{"role": "system", "content": REPORT_WRITING_PROMPT}]
    chat_messages.append({"role": "system", "content": user_payload})
    for item in messages:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})

    if provider == "ollama":
        return _ollama_messages(chat_messages, max_tokens=2200)
    if provider == "groq":
        return _groq_messages(chat_messages, max_tokens=2200)
    if provider == "gemini":
        return _gemini_messages(chat_messages, max_tokens=2200)
    raise ValueError(f"Unknown AI provider: {provider}")


def _parse_report_writing_response(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        from .tasks import _extract_findings

        findings = _extract_findings(text)
        body = text
        for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
            if marker in body:
                body = body.split(marker, 1)[0].strip()
                break
        return {
            "executive_summary": body,
            "key_findings": findings,
            "assistant_reply": "Draft parsed from free-form model output.",
        }

    findings = data.get("key_findings") or []
    if isinstance(findings, str):
        findings = [line.strip() for line in findings.split("\n") if line.strip()]
    return {
        "executive_summary": str(data.get("executive_summary") or "").strip(),
        "key_findings": [str(f).strip() for f in findings if str(f).strip()][:8],
        "assistant_reply": str(data.get("assistant_reply") or "Draft ready for your review.").strip(),
    }


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
            f"{mineral_line} Intelligence summary unavailable ({'; '.join(errors[:2])}).",
            "fallback",
        )
    return (
        f"{mineral_line} Configure intelligence provider settings in .env for generated summaries.",
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
    user_msg = f"Mapped data for this map click in Tanzania:\n\n{context}"
    if provider == "ollama":
        return _ollama_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "groq":
        return _groq_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "gemini":
        return _gemini_custom(user_msg, MAP_INSIGHT_PROMPT)
    raise ValueError(f"Unknown AI provider: {provider}")


def _call_chat_provider(
    provider: str,
    messages: list[dict[str, str]],
    context: str,
) -> str:
    chat_messages = [{"role": "system", "content": ASSISTANT_CHAT_PROMPT}]
    if context.strip():
        chat_messages.append(
            {
                "role": "system",
                "content": f"Reference context (use only this data):\n{context.strip()}",
            }
        )
    for item in messages:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})

    if provider == "ollama":
        return _ollama_messages(chat_messages)
    if provider == "groq":
        return _groq_messages(chat_messages)
    if provider == "gemini":
        return _gemini_messages(chat_messages)
    raise ValueError(f"Unknown AI provider: {provider}")


def _ollama(context: str) -> str:
    return _ollama_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _groq(context: str) -> str:
    return _groq_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _gemini(context: str) -> str:
    return _gemini_custom(f"Summarize this mineral report:\n\n{context}", SYSTEM_PROMPT)


def _ollama_custom(user_content: str, system_prompt: str) -> str:
    return _ollama_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )


def _ollama_messages(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["message"]["content"]


def _groq_custom(user_content: str, system_prompt: str) -> str:
    return _groq_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )


def _groq_messages(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.35,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _gemini_custom(user_content: str, system_prompt: str) -> str:
    return _gemini_messages(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )


def _gemini_messages(messages: list[dict[str, str]], max_tokens: int = 900) -> str:
    model = settings.GEMINI_MODEL
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.GEMINI_API_KEY}"
    )
    parts = []
    for item in messages:
        role = item.get("role", "user")
        content = item.get("content", "")
        prefix = "System" if role == "system" else ("User" if role == "user" else "Assistant")
        parts.append(f"{prefix}: {content}")
    payload = {
        "contents": [{"parts": [{"text": "\n\n".join(parts)}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35},
    }
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _fallback_region_line(context: str) -> str:
    try:
        region = context.split("Administrative region at click:")[1].split("\n")[0].strip()
        if region:
            return f"This area is in {region}, Tanzania."
    except (IndexError, AttributeError):
        pass
    try:
        region = context.split("Mapped zone region")[1].split("\n")[0].strip()
        if region:
            return f"This area is in {region}, Tanzania."
    except (IndexError, AttributeError):
        pass
    return "This area is in Tanzania."


def _fallback_mineral_line(context: str) -> str:
    try:
        mineral = context.split("Mineral:")[1].split("\n")[0].strip()
        return f"This report covers {mineral} prospectivity in Tanzania."
    except (IndexError, AttributeError):
        return "This report covers mineral prospectivity in Tanzania."
