"""Tanzania mobile number normalization for SMS OTP and payments."""

from __future__ import annotations

import re

TZ_MOBILE_RE = re.compile(r"^7[0-9]{8}$")


def normalize_tz_phone(value: str | None) -> str | None:
    """Return canonical international digits (2557XXXXXXXX) or None if invalid."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value).strip())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("255"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if not TZ_MOBILE_RE.fullmatch(national):
        return None
    return f"255{national}"


def beem_dest_addr(phone: str) -> str:
    """Beem API destination: international format without leading +."""
    normalized = normalize_tz_phone(phone)
    if not normalized:
        raise ValueError("Invalid phone number.")
    return normalized


def format_tz_phone_display(phone: str) -> str:
    normalized = normalize_tz_phone(phone)
    if not normalized:
        return phone
    local = normalized[3:]
    return f"0{local[:3]} {local[3:6]} {local[6:]}"
