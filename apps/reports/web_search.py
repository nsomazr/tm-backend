import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_WEB_CONTEXT_CHARS = 6000
REFERENCES_HEADING = "References and Sources"


class WebSearchSource:
    __slots__ = ("title", "url")

    def __init__(self, title: str, url: str) -> None:
        self.title = (title or "Untitled").strip()
        self.url = (url or "").strip()


class WebSearchResult:
    __slots__ = ("context_text", "sources")

    def __init__(self, context_text: str, sources: list[WebSearchSource]) -> None:
        self.context_text = context_text
        self.sources = sources


def build_report_search_query(metadata: dict, instruction: str) -> str:
    parts: list[str] = []
    mineral = (metadata.get("mineral_name") or "").strip()
    region = (metadata.get("region_name") or "").strip()
    title = (metadata.get("title") or "").strip()
    if mineral:
        parts.append(mineral)
    if region:
        parts.append(region)
    if title:
        parts.append(title)
    instruction_line = instruction.strip()[:240]
    if instruction_line:
        parts.append(instruction_line)
    base = " ".join(parts) or "mineral exploration geology"
    return f"{base} geological mineral exploration mining prospectivity"


def web_search_unavailable_reason() -> str | None:
    if not getattr(settings, "TAVILY_SEARCH_ENABLED", True):
        return "Web search is disabled on the server (TAVILY_SEARCH_ENABLED=false)."
    api_key = (getattr(settings, "TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        return "Tavily API key is not configured. Add TAVILY_API_KEY to tm-backend/.env and restart the backend."
    return None


def strip_references_section(text: str) -> str:
    if not text or not text.strip():
        return ""
    pattern = re.compile(
        rf"\n\s*{re.escape(REFERENCES_HEADING)}\s*\n[\s\S]*$",
        re.IGNORECASE,
    )
    stripped = pattern.sub("", text.rstrip())
    return stripped.rstrip()


def append_web_references(report_text: str, sources: list[WebSearchSource]) -> str:
    if not sources:
        return report_text
    body = strip_references_section(report_text)
    lines = [REFERENCES_HEADING, ""]
    seen_urls: set[str] = set()
    index = 1
    for source in sources:
        if not source.url and not source.title:
            continue
        url_key = source.url.lower()
        if url_key and url_key in seen_urls:
            continue
        if url_key:
            seen_urls.add(url_key)
        if source.url:
            lines.append(f"{index}. {source.title} - {source.url}")
        else:
            lines.append(f"{index}. {source.title}")
        index += 1
    if index == 1:
        return report_text
    return f"{body}\n\n" + "\n".join(lines)


def search_web_for_report(
    metadata: dict,
    instruction: str,
    *,
    max_results: int | None = None,
) -> WebSearchResult:
    api_key = (getattr(settings, "TAVILY_API_KEY", "") or "").strip()
    if not api_key:
        logger.warning("Tavily web search skipped: TAVILY_API_KEY not configured")
        return WebSearchResult("", [])

    max_results = max_results or int(getattr(settings, "TAVILY_MAX_RESULTS", "5"))
    query = build_report_search_query(metadata, instruction)

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=35,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return WebSearchResult("", [])

    lines = [
        "Web research (third-party sources; verify facts and note data limitations in the report):"
    ]
    sources: list[WebSearchSource] = []
    answer = (data.get("answer") or "").strip()
    if answer:
        lines.append(f"Overview: {answer}")

    results = data.get("results") or []
    for idx, item in enumerate(results[:max_results], start=1):
        title = (item.get("title") or "Untitled").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or item.get("raw_content") or "").strip()
        if not content and not title and not url:
            continue
        snippet = content[:900] if content else title
        lines.append(f"\n[{idx}] {title}")
        if url:
            lines.append(f"Source: {url}")
            sources.append(WebSearchSource(title=title, url=url))
        if snippet:
            lines.append(snippet)

    text = "\n".join(lines).strip()
    if len(lines) <= 1:
        return WebSearchResult("", [])
    return WebSearchResult(text[:MAX_WEB_CONTEXT_CHARS], sources)
