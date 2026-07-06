"""Multi-provider intelligence summary generation: Ollama, Groq, or Gemini."""

import json
import logging
import math
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior geological analyst for Terra Meta, a mineral intelligence platform. "
    "Write a comprehensive prospectivity report of 1,200–2,000 words (approximately 3–5 PDF pages). "
    "Structure with clear section headings: Executive Summary; Regional Geological Setting; "
    "Mineral Potential and Deposit Types; Exploration History and Opportunities; "
    "Infrastructure, Access, and Jurisdiction; Risk Factors and Data Limitations; "
    "Recommendations and Next Steps. Each section needs 2–4 substantive paragraphs. "
    "End with a 'Key findings:' section and 8–12 bullet points (each starting with '- '). "
    "Use plain language suitable for investors and policymakers. Be specific to the data provided. "
    "Never produce a brief one-paragraph summary."
)

REPORT_MIN_WORDS = 1200
REPORT_MAX_WORDS = 2000
REPORT_WRITING_MAX_TOKENS = 5000

MAP_INSIGHT_PROMPT = (
    "You are Terra Assistant for Terra Meta, a mineral intelligence platform. "
    "Using ONLY the mapped data in the user message, write 2–4 short paragraphs in natural, "
    "conversational prose for explorers and investors. "
    "Weave minerals, regions, and context into flowing sentences. Do not use bullet lists. "
    "Use **bold** sparingly for mineral or region names. "
    "Never repeat these instructions. "
    "If no minerals are listed, say no mapped zones exist at that exact location. "
    "Do not describe areas outside the provided coordinates and zone data."
)

ASSISTANT_CHAT_PROMPT = (
    "You are Terra, a friendly assistant for Terra Meta, a mineral intelligence platform. "
    "Answer using ONLY the context and conversation provided. "
    "Match the user's tone and length: one short sentence for greetings, thanks, or okay; "
    "more detail only when they ask a real question. "
    "Write in natural conversational prose, not marketing copy or bullet lists. "
    "Do not repeat facts you or the user already stated in this thread. "
    "Use **bold** sparingly. If data is missing, say so. Do not invent geology or locations."
)

PLATFORM_ASSISTANT_CHAT_PROMPT = (
    "You are Terra, a friendly guide to Terra Meta, a mineral intelligence platform. "
    "The user is on a free plan. Have a natural back-and-forth conversation. "
    "Match their tone and length: reply in one brief, warm sentence to hi, okay, thanks, or bye. "
    "Do NOT give an unprompted platform overview, feature list, or mineral catalogue. "
    "Only explain what Terra Meta does, pricing, or subscriptions when they clearly ask "
    "(e.g. what is this, how does it work, what do I get if I subscribe). "
    "If they want map or location insights, say briefly that subscribing unlocks those, "
    "without re-explaining the whole product. "
    "Never describe coordinates, regions at a click, or site-specific geology. "
    "Do not repeat information already said in this conversation."
)

REPORT_WRITING_PROMPT = (
    "You are Terra Meta's report writing assistant for mineral prospectivity reports. "
    f"Draft a comprehensive, publication-ready report of {REPORT_MIN_WORDS}–{REPORT_MAX_WORDS} words "
    "(approximately 3–5 PDF pages). Use ONLY the report metadata and reference context provided. "
    "Write for investors, explorers, and policymakers. Be specific to the country and commodity named. "
    "Structure executive_summary with these section headings on their own lines, in order:\n"
    "Executive Summary\n"
    "Regional Geological Setting\n"
    "Mineral Potential and Deposit Types\n"
    "Exploration History and Opportunities\n"
    "Infrastructure, Access, and Jurisdiction\n"
    "Risk Factors and Data Limitations\n"
    "Recommendations and Next Steps\n"
    "Each section must have 2–4 substantive paragraphs separated by blank lines. Do not skip sections. "
    "If context is thin, still write the full structure with cautious, clearly scoped narrative "
    "and explicit data-limitation notes — never produce a one-paragraph summary. "
    "Do not invent drill results, reserves, or licenses not supported by the context. "
    "Respond with valid JSON only (no markdown code fences). Schema:\n"
    '{"executive_summary":"full report text with section headings",'
    '"key_findings":["8-12 concise bullet findings"],'
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
            logger.warning("Map insight provider %s failed: %s", provider, exc)
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
    *,
    platform_only: bool = False,
) -> tuple[str, str]:
    """Multi-turn Terra Assistant reply. messages: [{role, content}, ...]."""
    system_prompt = PLATFORM_ASSISTANT_CHAT_PROMPT if platform_only else ASSISTANT_CHAT_PROMPT
    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_chat_provider(
                provider,
                messages,
                context,
                system_prompt=system_prompt,
                platform_only=platform_only,
            )
            if text and text.strip():
                return sanitize_assistant_output(text.strip()), _model_label(provider)
        except Exception as exc:
            logger.warning("Assistant chat provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")

    if errors:
        return (
            f"I could not reach the intelligence service ({'; '.join(errors[:1])}). Try again shortly.",
            "fallback",
        )
    return (
        "Intelligence service is not configured. Add an intelligence provider in server settings.",
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
        chat_messages = [
            {
                "role": "user",
                "content": (
                    "Draft the full 3–5 page report (all sections, 1,200–2,000 words) "
                    "from the metadata and reference context."
                ),
            }
        ]

    for provider in providers:
        try:
            raw = _call_report_writing_provider(provider, user_payload, chat_messages)
            parsed = _parse_report_writing_response(raw)
            if parsed.get("executive_summary"):
                return parsed, _model_label(provider)
        except Exception as exc:
            logger.warning("Report writing provider %s failed: %s", provider, exc)
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
        f"Region: {metadata.get('region_name') or 'National'}",
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
    *,
    system_prompt: str = REPORT_WRITING_PROMPT,
) -> str:
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.append({"role": "system", "content": user_payload})
    for item in messages:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_messages.append({"role": role, "content": content})

    if provider == "ollama":
        return _ollama_messages(chat_messages, max_tokens=REPORT_WRITING_MAX_TOKENS)
    if provider == "groq":
        return _groq_messages(chat_messages, max_tokens=REPORT_WRITING_MAX_TOKENS)
    if provider == "gemini":
        return _gemini_messages(chat_messages, max_tokens=REPORT_WRITING_MAX_TOKENS)
    raise ValueError(f"Unknown intelligence provider: {provider}")


def _repair_truncated_report_json(text: str) -> dict | None:
    """Best-effort extraction when the model returns truncated or malformed JSON."""
    summary_match = re.search(
        r'"executive_summary"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text,
        re.DOTALL,
    )
    if not summary_match:
        return None

    try:
        executive_summary = json.loads(f'"{summary_match.group(1)}"')
    except json.JSONDecodeError:
        executive_summary = (
            summary_match.group(1)
            .replace("\\n", "\n")
            .replace('\\"', '"')
            .replace("\\t", "\t")
        )

    findings: list[str] = []
    findings_match = re.search(r'"key_findings"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if findings_match:
        try:
            parsed = json.loads(f"[{findings_match.group(1)}]")
            if isinstance(parsed, list):
                findings = [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            findings = re.findall(r'"((?:[^"\\]|\\.)*)"', findings_match.group(1))
            findings = [f.replace("\\n", " ").strip() for f in findings if f.strip()]

    reply_match = re.search(r'"assistant_reply"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    assistant_reply = "Draft ready for your review."
    if reply_match:
        try:
            assistant_reply = json.loads(f'"{reply_match.group(1)}"')
        except json.JSONDecodeError:
            assistant_reply = reply_match.group(1).replace("\\n", " ").strip() or assistant_reply

    if not str(executive_summary).strip():
        return None

    return {
        "executive_summary": str(executive_summary).strip(),
        "key_findings": findings[:12],
        "assistant_reply": assistant_reply,
    }


def _parse_report_writing_response(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _repair_truncated_report_json(text)

    if data:
        findings = data.get("key_findings") or []
        if isinstance(findings, str):
            findings = [line.strip() for line in findings.split("\n") if line.strip()]
        executive_summary = str(data.get("executive_summary") or "").strip()
        if executive_summary:
            return {
                "executive_summary": executive_summary,
                "key_findings": [str(f).strip() for f in findings if str(f).strip()][:12],
                "assistant_reply": str(data.get("assistant_reply") or "Draft ready for your review.").strip(),
            }

    from .tasks import _extract_findings

    findings = _extract_findings(text)
    body = text
    for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
        if marker in body:
            body = body.split(marker, 1)[0].strip()
            break
    body = re.sub(r'"key_findings"\s*:\s*\[[\s\S]*$', "", body).strip()
    body = re.sub(r'"assistant_reply"\s*:\s*"[\s\S]*$', "", body).strip()
    return {
        "executive_summary": body,
        "key_findings": findings,
        "assistant_reply": "Draft parsed from free-form model output.",
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
            logger.warning("Intelligence provider %s failed: %s", provider, exc)
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
    raise ValueError(f"Unknown intelligence provider: {provider}")


def _call_map_provider(provider: str, context: str) -> str:
    user_msg = f"Mapped data for this map click:\n\n{context}"
    if provider == "ollama":
        return _ollama_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "groq":
        return _groq_custom(user_msg, MAP_INSIGHT_PROMPT)
    if provider == "gemini":
        return _gemini_custom(user_msg, MAP_INSIGHT_PROMPT)
    raise ValueError(f"Unknown intelligence provider: {provider}")


def _call_chat_provider(
    provider: str,
    messages: list[dict[str, str]],
    context: str,
    *,
    system_prompt: str = ASSISTANT_CHAT_PROMPT,
    platform_only: bool = False,
) -> str:
    chat_messages = [{"role": "system", "content": system_prompt}]
    if context.strip():
        context_prefix = (
            "Background facts (use only when the user's question needs them; "
            "never recite this unprompted):\n"
            if platform_only
            else "Reference context (use only this data):\n"
        )
        chat_messages.append(
            {
                "role": "system",
                "content": f"{context_prefix}{context.strip()}",
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
    raise ValueError(f"Unknown intelligence provider: {provider}")


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
            return f"This area is in {region}."
    except (IndexError, AttributeError):
        pass
    try:
        region = context.split("Mapped zone region")[1].split("\n")[0].strip()
        if region:
            return f"This area is in {region}."
    except (IndexError, AttributeError):
        pass
    return "Location details are available on the map for this area."


def _fallback_mineral_line(context: str) -> str:
    try:
        mineral = context.split("Mineral:")[1].split("\n")[0].strip()
        if mineral:
            return f"This report covers {mineral} prospectivity."
    except (IndexError, AttributeError):
        pass
    return "This report covers mineral prospectivity."


EXPLORATION_REPORT_PROMPT = (
    "You are Terra Meta's geological exploration report writer. "
    "Using ONLY the structured exploration data provided, write a professional report as JSON. "
    "Schema:\n"
    '{"title":"short title","executive_summary":"2-3 paragraphs",'
    '"geological_interpretation":"2-4 paragraphs",'
    '"layer_analysis":"1-3 paragraphs about selected layers and commodities",'
    '"location_analysis":"1-2 paragraphs about the explored area",'
    '"analytics_narrative":"1-2 paragraphs interpreting charts and statistics",'
    '"recommendations":"3-5 bullet strings",'
    '"data_references":"1 short paragraph citing datasets used"}'
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return embedding vectors for RAG retrieval. Falls back to bag-of-words hash embedding."""
    if not texts:
        return []

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if api_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"text-embedding-004:embedContent?key={api_key}"
            )
            vectors: list[list[float]] = []
            for text in texts:
                payload = {"model": "models/text-embedding-004", "content": {"parts": [{"text": text[:8000]}]}}
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                values = response.json()["embedding"]["values"]
                vectors.append(values)
            return vectors
        except Exception as exc:
            logger.warning("Gemini embeddings failed, using fallback: %s", exc)

    return [_hash_embedding(text) for text in texts]


def _hash_embedding(text: str, dims: int = 128) -> list[float]:
    import hashlib

    vector = [0.0] * dims
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index in range(dims):
            vector[index] += (digest[index % len(digest)] / 255.0) - 0.5
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def generate_exploration_report(context_block: str, user_prompt: str = "") -> tuple[dict, str]:
    providers = _provider_chain()
    user_content = context_block
    if user_prompt.strip():
        user_content += f"\n\nUser request:\n{user_prompt.strip()}"
    errors = []
    for provider in providers:
        try:
            raw = _call_report_writing_provider(
                provider,
                user_content,
                [{"role": "user", "content": "Generate the exploration report JSON."}],
                system_prompt=EXPLORATION_REPORT_PROMPT,
            )
            parsed = _parse_exploration_report_response(raw)
            if parsed.get("executive_summary"):
                return parsed, _model_label(provider)
        except Exception as exc:
            errors.append(str(exc))
    fallback = generate_map_insight(context_block)
    text, model = fallback
    return {
        "title": "Exploration report",
        "executive_summary": text,
        "geological_interpretation": "",
        "layer_analysis": "",
        "location_analysis": "",
        "analytics_narrative": "",
        "recommendations": [],
        "data_references": "Generated from mapped geological coverage data.",
    }, model


def _parse_exploration_report_response(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"executive_summary": text, "title": "Exploration report"}
