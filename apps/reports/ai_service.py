"""Multi-provider intelligence summary generation: Ollama, Groq, or Gemini."""

import json
import logging
import math
import re

import requests
from django.conf import settings

from .report_text_utils import filter_report_findings, normalize_section_heading

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior geological analyst for Terra Meta, a mineral intelligence platform. "
    "Write a comprehensive prospectivity report of 1,200-2,000 words (approximately 3-5 PDF pages). "
    "Choose a structure that fits the commodity, region, and brief: full assessment, regional memo, "
    "investor note, or technical summary. Use clear section headings on their own lines. "
    "Typical sections include Executive Summary, Regional Geological Setting, Mineral Potential, "
    "Exploration History, Infrastructure and Jurisdiction, Risks, and Recommendations, "
    "but omit or rename sections that do not fit. "
    "Each substantive section needs 2-4 paragraphs. "
    "End with a 'Key findings:' section and 8-12 bullet points (each starting with '- '). "
    "Key findings must be geological or investment insights, not bibliographic titles. "
    "Use plain language suitable for investors and policymakers. Be specific to the data provided. "
    "Never produce a brief one-paragraph summary. Never use em dashes or en dashes; use commas, periods, colons, or hyphens."
)

REPORT_MIN_WORDS = 1200
REPORT_MAX_WORDS = 2000
REPORT_WRITING_MAX_TOKENS = 5000


def _redact_secrets(text: str) -> str:
    text = re.sub(r"(key=)[^&\s\"']+", r"\1***", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s)\S+", r"\1***", text, flags=re.IGNORECASE)
    return text


def friendly_provider_error(provider: str, exc: Exception) -> str:
    msg = _redact_secrets(str(exc))
    lower = msg.lower()
    if "429" in lower or "too many requests" in lower:
        return f"{provider}: rate limit reached — try again shortly"
    if provider == "ollama" and ("404" in lower or "not found" in lower):
        return f"{provider}: no chat model available"
    if len(msg) > 120:
        msg = msg[:117] + "…"
    return f"{provider}: unavailable"


def _post_with_rate_limit_retry(**kwargs):
    response = requests.post(**kwargs)
    response.raise_for_status()
    return response


MAP_INSIGHT_PROMPT = (
    "You are Terra Meta's senior exploration geologist. "
    "Using ONLY the mapped data in the user message, write 4-5 substantive paragraphs "
    "(roughly 280-420 words) for mineral explorers and investors. "
    "Cover: location and analysis scope; mapped point occurrences and polygon mineral areas "
    "with exact counts (occurrence = point feature only); "
    "compass-direction clustering relative to the analysis center when sector counts are provided; "
    "mapped structure orientations (geological trend/strike) when provided — treat these as fabric, "
    "distinct from compass clustering of features around the analysis center; "
    "geological and exploration implications for each commodity listed; a recommended "
    "field program (mapping, sampling, geophysics, licensing); and data limitations. "
    "Write flowing geological prose in natural paragraphs. Do not use bullet lists or markdown headings. "
    "Use **bold** sparingly for mineral and region names only. "
    "If minerals are listed in the analysis area, describe them; never claim there are no mapped areas. "
    "Use the word occurrence only for mapped point features; call polygons mineral areas or coverage. "
    "When compass distribution data is included, describe how areas lie north/south/east/west of the "
    "analysis center and note commodity-specific directional clustering only when supported by the counts. "
    "When structure orientation data is included, describe dominant trends (for example NE–SW) using "
    "only those counts; do not invent fold axes, fault sense, or dip. "
    "When geological reference from administrative boundaries is included, integrate it with mapped "
    "mineral data to explain regional setting, stratigraphy, and exploration implications. "
    "When terrain elevation metrics are included, describe surface relief and landform character only; "
    "do not equate lowland or flat terrain with sedimentary basins unless geological reference supports it. "
    "When a map view type is specified (satellite, terrain, etc.), tailor emphasis to what that view "
    "highlights, but never invent features not supported by the data or image. "
    "Use only administrative names and geography provided; do not invent coastlines, reserves, "
    "drill intercepts, or deposit models not supported by the data."
)

TERRAIN_VISUAL_INSIGHT_PROMPT = (
    "You are Terra Meta's senior exploration geologist with access to a map screenshot and "
    "structured exploration data. Using ONLY the image and text context provided, write 4-5 "
    "substantive paragraphs (roughly 280-420 words) for mineral explorers and investors. "
    "Describe visible landforms cautiously: ridges, valleys, drainage, vegetation, exposed rock, "
    "and lineaments only when you can see them in the image. Cross-check visual observations "
    "with mapped mineral counts, terrain elevation metrics, and geological reference text. "
    "Mapped mineral data is authoritative for commodity presence and counts; the image is "
    "supplementary context. Never invent drill results, reserves, basin names, or deposit models. "
    "Do not claim sedimentary basin setting from low relief alone. "
    "Write flowing geological prose in natural paragraphs without bullet lists or markdown headings. "
    "Use **bold** sparingly for mineral and region names only."
)

GEOLOGICAL_MAP_INSIGHT_PROMPT = MAP_INSIGHT_PROMPT

EXPORT_NARRATIVE_PROMPT = (
    "You are Terra Meta's mineral intelligence report writer. Using ONLY the structured data below, "
    "write a professional brief suitable for 3–5 printed pages (roughly 900–1400 words). "
    "Use plain section titles on their own lines (no # or ### markdown, no asterisk bullets). "
    "Separate sections with a blank line. Suggested sections: Executive Summary, Mineral Coverage, "
    "Regional Distribution, Analysis and Trends, Recommendations. "
    "Write in clear paragraphs for investors and exploration teams. "
    "Use short bullet lines starting with a hyphen only when listing minerals or regions. "
    "Cite specific numbers, regions, and minerals from the data. "
    "When an exploration area is specified, describe ONLY minerals inside that drawn area. "
    "Do not summarize the whole country or entire map dataset. "
    "Do not invent reserves, licenses, or drill results. "
    "If data is limited, state that clearly."
)

ASSISTANT_CHAT_PROMPT = (
    "You are Terra, a friendly assistant for Terra Meta, a mineral intelligence platform. "
    "Answer using ONLY the context and conversation provided. "
    "When the context specifies a user-drawn exploration area, discuss ONLY minerals inside that geometry. "
    "Do not summarize the entire map or country unless the user explicitly asks for a broader view. "
    "When map view type, terrain elevation metrics, or visual landform context are included, use them "
    "to answer questions about what the user sees or why minerals might occur in that setting, but never "
    "invent geology not supported by the context. Do not equate lowland terrain with sedimentary basins "
    "unless geological reference data supports it. "
    "Match the user's tone and length: one short sentence for greetings, thanks, or okay; "
    "more detail only when they ask a real question. "
    "Write in natural conversational prose, not marketing copy or bullet lists. "
    "Do not use markdown headings (# or ###). "
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
    f"Draft a comprehensive, publication-ready report of {REPORT_MIN_WORDS}-{REPORT_MAX_WORDS} words "
    "(approximately 3-5 PDF pages). Use the report metadata and reference context provided "
    "(uploaded documents, notes, and optional web research). When web research is included, "
    "treat it as supplementary, verify claims, and note third-party or limited data sources. "
    "Write for investors, explorers, and policymakers. Be specific to the country and commodity named. "
    "Choose a structure that fits the user's instruction and report type (full prospectivity assessment, "
    "regional brief, commodity overview, technical memo, investor note, etc.). "
    "Use clear section headings on their own lines (plain text, no ** or #). "
    "Typical sections include Executive Summary, Regional Geological Setting, Mineral Potential, "
    "Exploration History, Infrastructure and Jurisdiction, Risks, and Recommendations, "
    "but omit or rename sections that do not fit the brief. "
    "A short memo may use 4-5 sections; a full assessment may use 6-8 with 2-4 paragraphs each. "
    f"Target {REPORT_MIN_WORDS}-{REPORT_MAX_WORDS} words for a full assessment; scale down proportionally for briefs. "
    "If context is thin, still write a coherent structure with cautious, clearly scoped narrative "
    "and explicit data-limitation notes. Never produce a one-paragraph summary. "
    "Never return key_findings alone: executive_summary must always contain the full report body. "
    "key_findings must be 8-12 concise geological or investment findings only. "
    "Never put bibliographic citations, paper titles, PDF names, or URLs in key_findings. "
    "Place all web and document sources only under a References and Sources section at the end of executive_summary. "
    "Do not include any conversational introduction, preamble, or horizontal rules in executive_summary. "
    "Do not use markdown dividers such as --- or ***. "
    "Start executive_summary directly with the Executive Summary section heading as the first line. "
    "When refining an existing draft, preserve unchanged sections and apply the user's instruction to the rest. "
    "When the user asks to rewrite or regenerate the full report, return a complete new executive_summary "
    f"({REPORT_MIN_WORDS}+ words) with all sections. "
    "Never use em dashes or en dashes. Use commas, periods, colons, or hyphens instead. "
    "Do not invent drill results, reserves, or licenses not supported by the context. "
    "Respond with valid JSON only (no markdown code fences). Schema:\n"
    '{"executive_summary":"full report text with section headings",'
    '"key_findings":["8-12 concise bullet findings"],'
    '"assistant_reply":"1-2 sentences explaining what you drafted or changed"}'
)

REPORT_WRITING_MIN_BODY_WORDS = 35

REGENERATE_INSTRUCTION_RE = re.compile(
    r"\b(rewrite|regenerate|start over|from scratch|redo|write again|whole report|full report|new draft|replace all|rebuild)\b",
    re.IGNORECASE,
)

REPORT_SECTION_HEADINGS = (
    "Executive Summary",
    "Regional Geological Setting",
    "Mineral Potential and Deposit Types",
    "Exploration History and Opportunities",
    "Infrastructure, Access, and Jurisdiction",
    "Risk Factors and Data Limitations",
    "Recommendations and Next Steps",
    "References and Sources",
)

FREE_ASSISTANT_FOLLOWUP_LIMIT = 3  # deprecated: use assistant credits


def _normalize_report_heading_line(line: str) -> str:
    return normalize_section_heading(line)


def _is_report_section_heading(line: str) -> bool:
    normalized = _normalize_report_heading_line(line)
    if normalized in REPORT_SECTION_HEADINGS:
        return True
    lower = normalized.lower()
    return any(heading.lower() == lower for heading in REPORT_SECTION_HEADINGS)


def strip_report_preamble(text: str) -> str:
    """Drop assistant filler before the first standard report section heading."""
    if not text or not text.strip():
        return text or ""
    before_words = len(text.split())
    lines = text.splitlines()
    start = -1
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line or re.match(r"^[-*_]{3,}\s*$", line):
            continue
        if _is_report_section_heading(line):
            start = index
            break
    if start <= 0:
        return text.strip()
    stripped = "\n".join(lines[start:]).strip()
    after_words = len(stripped.split())
    if before_words >= 80 and after_words < max(40, int(before_words * 0.25)):
        return text.strip()
    return stripped


def sanitize_report_text(text: str) -> str:
    """Normalize report copy: no em/en dashes in published output."""
    if not text:
        return text
    cleaned = text.replace("\u2014", ", ").replace("\u2013", "-")
    cleaned = re.sub(r",\s+,", ", ", cleaned)
    cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
    normalized_lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            normalized_lines.append("")
            continue
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            normalized_lines.append("")
            continue
        bold_heading = re.match(r"^\*\*(.+?)\*\*:?\s*$", stripped)
        if bold_heading:
            normalized_lines.append(bold_heading.group(1).strip())
            continue
        hash_heading = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if hash_heading:
            normalized_lines.append(hash_heading.group(1).strip())
            continue
        normalized_lines.append(line)
    return strip_report_preamble("\n".join(normalized_lines).strip())


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
        "3-5 short",
    )
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if any(lower.startswith(prefix) for prefix in skip_prefixes):
            continue
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or text.strip()


def generate_map_insight(context: str) -> tuple[str, str]:
    """Generate location-based map insights. Returns (insight_text, model_used)."""
    return generate_geological_map_insight(context)


def generate_geological_map_insight(
    context: str,
    *,
    image_b64: str | None = None,
) -> tuple[str, str]:
    """Geological exploration narrative for map clicks. Returns (insight_text, model_used)."""
    if image_b64:
        from apps.analytics.ai_settings import vision_provider_chain

        user_msg = f"Mapped exploration data for this location:\n\n{context}"
        for provider in vision_provider_chain():
            try:
                if provider == "gemini":
                    text = _gemini_vision(TERRAIN_VISUAL_INSIGHT_PROMPT, user_msg, image_b64)
                elif provider == "ollama":
                    text = _ollama_vision(TERRAIN_VISUAL_INSIGHT_PROMPT, user_msg, image_b64)
                else:
                    continue
                if text and text.strip():
                    return sanitize_assistant_output(text.strip()), _model_label(provider)
            except Exception as exc:
                logger.warning("Vision map insight provider %s failed: %s", provider, exc)

    providers = _provider_chain()
    errors = []

    for provider in providers:
        try:
            text = _call_geological_map_provider(provider, context)
            if text and text.strip():
                return sanitize_assistant_output(text.strip()), _model_label(provider)
        except Exception as exc:
            logger.warning("Geological map insight provider %s failed: %s", provider, exc)
            errors.append(friendly_provider_error(provider, exc))

    return "fallback", "fallback"


def _call_geological_map_provider(provider: str, context: str) -> str:
    user_msg = f"Mapped exploration data for this location:\n\n{context}"
    if provider == "ollama":
        return _ollama_custom(user_msg, GEOLOGICAL_MAP_INSIGHT_PROMPT)
    if provider == "groq":
        return _groq_custom(user_msg, GEOLOGICAL_MAP_INSIGHT_PROMPT)
    if provider == "gemini":
        return _gemini_custom(user_msg, GEOLOGICAL_MAP_INSIGHT_PROMPT)
    raise ValueError(f"Unknown intelligence provider: {provider}")


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
            errors.append(friendly_provider_error(provider, exc))

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

    chat_messages = list(messages or [])
    if _should_treat_as_fresh_draft(chat_messages, current_draft):
        current_draft = None

    user_payload = _build_report_writing_user_payload(metadata, context_text, current_draft)
    if not chat_messages:
        chat_messages = [
            {
                "role": "user",
                "content": (
                    "Draft the full 3-5 page report (all sections, 1,200-2,000 words) "
                    "from the metadata and reference context."
                ),
            }
        ]

    for provider in providers:
        try:
            raw = _call_report_writing_provider(provider, user_payload, chat_messages)
            parsed = _parse_report_writing_response(raw)
            if _report_body_is_substantive(parsed.get("executive_summary")):
                return parsed, _model_label(provider)
        except Exception as exc:
            logger.warning("Report writing provider %s failed: %s", provider, exc)
            errors.append(friendly_provider_error(provider, exc))

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
        _finalize_writing_draft(body, findings, reply),
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
        lines.append("\nReference context (uploaded documents, notes, and optional web research):")
        lines.append(context_text.strip()[:14000])
    return "\n".join(lines)


def _draft_body_word_count(draft: dict | None) -> int:
    if not draft:
        return 0
    text = (draft.get("executive_summary") or "").strip()
    return len(text.split()) if text else 0


def _is_regenerate_request(messages: list[dict[str, str]]) -> bool:
    for item in messages:
        if item.get("role") != "user":
            continue
        content = (item.get("content") or "").strip()
        if content and REGENERATE_INSTRUCTION_RE.search(content):
            return True
    return False


def _should_treat_as_fresh_draft(messages: list[dict[str, str]], current_draft: dict | None) -> bool:
    if _is_regenerate_request(messages):
        return True
    return _draft_body_word_count(current_draft) < REPORT_WRITING_MIN_BODY_WORDS


def _report_body_is_substantive(executive_summary: str | None) -> bool:
    text = (executive_summary or "").strip()
    if not text:
        return False
    return len(text.split()) >= REPORT_WRITING_MIN_BODY_WORDS


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


def _finalize_writing_draft(executive_summary: str, findings, assistant_reply: str) -> dict:
    raw_findings: list = findings if isinstance(findings, list) else []
    if isinstance(findings, str):
        raw_findings = [line.strip() for line in findings.splitlines() if line.strip()]
    cleaned_findings = filter_report_findings(
        [sanitize_report_text(str(item).strip()) for item in raw_findings if str(item).strip()]
    )[:12]
    return {
        "executive_summary": sanitize_report_text(str(executive_summary or "").strip()),
        "key_findings": cleaned_findings,
        "assistant_reply": str(assistant_reply or "Draft ready for your review.").strip(),
    }


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

    return _finalize_writing_draft(str(executive_summary).strip(), findings, assistant_reply)


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
        if _report_body_is_substantive(executive_summary):
            return _finalize_writing_draft(
                executive_summary,
                findings,
                str(data.get("assistant_reply") or "Draft ready for your review."),
            )

    from .tasks import _extract_findings

    findings = _extract_findings(text)
    body = text
    for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
        if marker in body:
            body = body.split(marker, 1)[0].strip()
            break
    body = re.sub(r'"key_findings"\s*:\s*\[[\s\S]*$', "", body).strip()
    body = re.sub(r'"assistant_reply"\s*:\s*"[\s\S]*$', "", body).strip()
    if not _report_body_is_substantive(body):
        return _finalize_writing_draft("", findings, "Model returned an incomplete draft.")

    return _finalize_writing_draft(body, findings, "Draft parsed from free-form model output.")


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
            errors.append(friendly_provider_error(provider, exc))

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
    from apps.analytics.ai_settings import provider_chain

    return provider_chain()


def _provider_configured(provider: str) -> bool:
    from apps.analytics.ai_settings import provider_configured

    return provider_configured(provider)


def _model_label(provider: str) -> str:
    if provider == "ollama":
        from apps.analytics.ai_settings import ollama_resolve_model

        resolved = ollama_resolve_model()
        if resolved:
            return f"ollama/{resolved}"
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


def _call_export_narrative_provider(provider: str, context: str) -> str:
    user_msg = f"Report data:\n\n{context}"
    if provider == "ollama":
        return _ollama_custom(user_msg, EXPORT_NARRATIVE_PROMPT)
    if provider == "groq":
        return _groq_custom(user_msg, EXPORT_NARRATIVE_PROMPT)
    if provider == "gemini":
        return _gemini_custom(user_msg, EXPORT_NARRATIVE_PROMPT)
    raise ValueError(f"Unknown intelligence provider: {provider}")


def generate_export_narrative_text(context: str) -> tuple[str, str]:
    """Long-form PDF narrative for Terra insight exports."""
    providers = _provider_chain()
    errors = []
    for provider in providers:
        try:
            text = _call_export_narrative_provider(provider, context)
            if text and text.strip():
                return sanitize_report_text(text.strip()), _model_label(provider)
        except Exception as exc:
            logger.warning("Export narrative provider %s failed: %s", provider, exc)
            errors.append(friendly_provider_error(provider, exc))
    if errors:
        return (
            f"Report narrative unavailable ({'; '.join(errors[:2])}).",
            "fallback",
        )
    return ("Report narrative is not configured.", "fallback")


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
    from apps.analytics.ai_settings import ollama_resolve_model, _ollama_active_base

    model = ollama_resolve_model()
    base = _ollama_active_base()
    if not model or not base:
        configured = getattr(settings, "OLLAMA_MODEL", "llama3.2")
        raise RuntimeError(
            f"No chat-capable Ollama model found. Run `ollama pull {configured}` or install a chat model."
        )

    url = f"{base.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    response = requests.post(url, json=payload, timeout=90)
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
    response = _post_with_rate_limit_retry(url=url, headers=headers, json=payload, timeout=60)
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
    response = _post_with_rate_limit_retry(url=url, json=payload, timeout=60)
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _normalize_image_b64(image_b64: str) -> tuple[str, str]:
    raw = image_b64.strip()
    match = re.match(r"data:image/(png|jpeg|jpg|webp);base64,(.+)", raw, re.DOTALL | re.IGNORECASE)
    if match:
        mime = "image/jpeg" if match.group(1).lower() in ("jpg", "jpeg") else f"image/{match.group(1).lower()}"
        return mime, re.sub(r"\s+", "", match.group(2))
    return "image/jpeg", re.sub(r"\s+", "", raw)


def _gemini_vision(system_prompt: str, user_content: str, image_b64: str, max_tokens: int = 900) -> str:
    mime, payload_b64 = _normalize_image_b64(image_b64)
    model = settings.GEMINI_MODEL
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.GEMINI_API_KEY}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": f"System: {system_prompt}\n\nUser: {user_content}"},
                    {"inline_data": {"mime_type": mime, "data": payload_b64}},
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35},
    }
    response = _post_with_rate_limit_retry(url=url, json=body, timeout=90)
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _ollama_vision(system_prompt: str, user_content: str, image_b64: str, max_tokens: int = 900) -> str:
    from apps.analytics.ai_settings import ollama_resolve_vision_model, _ollama_active_base

    model = ollama_resolve_vision_model()
    base = _ollama_active_base()
    if not model or not base:
        raise RuntimeError(
            "No vision-capable Ollama model found. Run `ollama pull llava` or set OLLAMA_VISION_MODEL."
        )

    _, payload_b64 = _normalize_image_b64(image_b64)
    url = f"{base.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content, "images": [payload_b64]},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["message"]["content"]


def _fallback_region_line(context: str) -> str:
    try:
        region = context.split("Administrative region at click:")[1].split("\n")[0].strip()
        if region:
            return f"This area is in {region}."
    except (IndexError, AttributeError):
        pass
    try:
        region = context.split("Mapped area region")[1].split("\n")[0].strip()
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
        "data_references": "Generated from mapped geological information.",
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
