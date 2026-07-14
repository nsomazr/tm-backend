"""Normalize structure orientation fields on map feature properties."""

from __future__ import annotations

import math
import re
from typing import Any

from apps.maps.geometry_utils import undirected_trend_degrees

# Common GIS / CAD column names for strike, trend, azimuth, bearing.
_ORIENTATION_ALIASES = frozenset(
    {
        "strike",
        "strike_deg",
        "strike_degree",
        "strike_degrees",
        "strikeazimuth",
        "strike_azimuth",
        "trend",
        "trend_deg",
        "trend_degree",
        "trend_degrees",
        "azimuth",
        "azimuth_deg",
        "azim",
        "az",
        "bearing",
        "bearing_deg",
        "orient",
        "orientation",
        "direction",
        "struc_dir",
        "struct_dir",
        "structure_dir",
        "structure_direction",
        "lineament_dir",
        "fault_dir",
        "fold_axis",
    }
)

_CANONICAL_TREND = "trend_deg"
_CANONICAL_STRIKE_180 = "strike_0_180"

_DEGREE_MARKERS = re.compile(r"[°º]|deg(?:rees?)?|d$", re.IGNORECASE)
_QUADRANT_RE = re.compile(
    r"^\s*([NS])\s*(\d+(?:\.\d+)?)\s*([EW])\s*$",
    re.IGNORECASE,
)


def parse_orientation_degrees(value: Any) -> float | None:
    """Parse a direction value into degrees clockwise from north (0–360), if possible."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return float(value) % 360.0

    text = str(value).strip()
    if not text:
        return None

    quadrant = _QUADRANT_RE.match(text)
    if quadrant:
        hemi_ns, mag_s, hemi_ew = quadrant.groups()
        mag = float(mag_s)
        if mag < 0 or mag > 90:
            return None
        ns = hemi_ns.upper()
        ew = hemi_ew.upper()
        if ns == "N" and ew == "E":
            return mag % 360.0
        if ns == "N" and ew == "W":
            return (360.0 - mag) % 360.0
        if ns == "S" and ew == "E":
            return (180.0 - mag) % 360.0
        if ns == "S" and ew == "W":
            return (180.0 + mag) % 360.0
        return None

    cleaned = _DEGREE_MARKERS.sub("", text).strip()
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned) % 360.0
    except ValueError:
        return None


def _alias_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def extract_orientation_degrees(props: dict[str, Any] | None) -> float | None:
    """Return the first parseable orientation from feature properties (0–360)."""
    if not isinstance(props, dict) or not props:
        return None

    # Prefer already-normalized keys.
    for preferred in (_CANONICAL_TREND, "strike_deg", "azimuth_deg", "bearing_deg"):
        if preferred in props:
            parsed = parse_orientation_degrees(props.get(preferred))
            if parsed is not None:
                return parsed

    for key, value in props.items():
        alias = _alias_key(key)
        alias_compact = alias.replace("_", "")
        if alias in _ORIENTATION_ALIASES or alias_compact in {
            a.replace("_", "") for a in _ORIENTATION_ALIASES
        }:
            parsed = parse_orientation_degrees(value)
            if parsed is not None:
                return parsed
    return None


def normalize_structure_properties(props: dict[str, Any] | None) -> dict[str, Any]:
    """
    Copy properties and write canonical trend_deg / strike_0_180 when an orientation is found.
    Does not remove original attribute keys.
    """
    out = dict(props or {})
    orientation = extract_orientation_degrees(out)
    if orientation is None:
        return out
    out[_CANONICAL_TREND] = round(orientation, 2)
    out[_CANONICAL_STRIKE_180] = round(undirected_trend_degrees(orientation), 2)
    return out
