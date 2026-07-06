"""Lightweight conversational helpers for Ask Terra."""

from __future__ import annotations

import re

_FILLER_WORDS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hiya",
        "ok",
        "okay",
        "k",
        "thanks",
        "thank",
        "you",
        "thx",
        "ty",
        "bye",
        "goodbye",
        "cool",
        "sure",
        "yes",
        "yeah",
        "yep",
        "yup",
        "no",
        "nope",
        "great",
        "nice",
        "alright",
        "sawa",
        "asante",
        "habari",
        "mambo",
        "poa",
        "ndio",
        "hapana",
    }
)


def is_lightweight_user_message(text: str) -> bool:
    """True for greetings, acknowledgments, and other very short social replies."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").strip().lower())
    words = [w for w in cleaned.split() if w]
    if not words or len(words) > 3:
        return False
    return all(word in _FILLER_WORDS for word in words)


def platform_filler_reply(question: str, locale: str = "en") -> str:
    q = (question or "").strip().lower()
    if locale == "sw":
        if any(token in q for token in ("asante", "thank", "thx")):
            return "Karibu! Nipo hapa ukiwa na swali kuhusu Terra Meta."
        if any(token in q for token in ("bye", "kwaheri")):
            return "Kwaheri! Rudi wakati wowote."
        if any(token in q for token in ("habari", "hello", "hi", "hey")):
            return "Habari! Ungependa kujua nini kuhusu Terra Meta?"
        return "Sawa! Una swali kuhusu jukwaa, au ungependa kujua kuhusu usajili?"
    if any(token in q for token in ("thank", "thx")):
        return "You're welcome! Happy to help with anything about Terra Meta."
    if "bye" in q:
        return "Goodbye! Come back anytime."
    if any(token in q for token in ("hi", "hello", "hey")):
        return "Hi! What would you like to know about Terra Meta?"
    return "Got it! Ask me about the platform or how subscriptions work."
