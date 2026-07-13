import colorsys
import re

from apps.minerals.geological_colors import match_geological_color

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

LAYER_COLOR_PALETTE = [
    "#0D9488",
    "#E87722",
    "#2563EB",
    "#7C3AED",
    "#DB2777",
    "#CA8A04",
    "#059669",
    "#DC2626",
    "#0891B2",
    "#9333EA",
    "#B45309",
    "#4F46E5",
    "#BE185D",
    "#0E7490",
    "#65A30D",
]


def normalize_hex(value: str, *, fallback: str = "#0D9488") -> str:
    raw = (value or "").strip()
    if not _HEX_RE.match(raw):
        return fallback
    body = raw.lstrip("#")
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    return f"#{body.upper()}"


def hex_to_rgba(hex_color: str, alpha: float = 0.55) -> str:
    hex_norm = normalize_hex(hex_color)
    body = hex_norm.lstrip("#")
    r = int(body[0:2], 16)
    g = int(body[2:4], 16)
    b = int(body[4:6], 16)
    alpha = max(0.0, min(1.0, float(alpha)))
    return f"rgba({r},{g},{b},{alpha:.2f})"


def rgba_for_layer_type(hex_color: str, layer_type: str) -> dict[str, str]:
    hex_norm = normalize_hex(hex_color)
    fill_alpha = 0.55 if layer_type == "polygon" else 0.72
    stroke_alpha = 0.95 if layer_type == "line" else 0.88
    return {
        "fillRgba": hex_to_rgba(hex_norm, fill_alpha),
        "strokeRgba": hex_to_rgba(hex_norm, stroke_alpha),
    }


def _hash_hue(seed: str) -> int:
    h = 0
    for ch in seed:
        h = ord(ch) + ((h << 5) - h)
    return abs(h) % 360


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def _unique_fallback(seed: str, used: set[str]) -> str:
    base = _hash_hue(seed or "layer")
    for i in range(360):
        hue = (base + i * 37) % 360
        hex_color = _hsl_to_hex(hue, 0.62, 0.42)
        if hex_color.lower() not in used:
            return hex_color
    return LAYER_COLOR_PALETTE[base % len(LAYER_COLOR_PALETTE)]


def suggest_layer_hex(
    layer_name: str = "",
    *,
    used_colors: list[str] | None = None,
    preferred_hex: str | None = None,
) -> str:
    """Pick an unused map color: geological match → preferred → palette → unique HSL."""
    used = {normalize_hex(c).lower() for c in (used_colors or []) if c}
    geological = match_geological_color(layer_name or "")
    if geological:
        geo = normalize_hex(geological)
        if geo.lower() not in used:
            return geo
    if preferred_hex:
        preferred = normalize_hex(preferred_hex)
        if preferred.lower() not in used:
            return preferred
    for color in LAYER_COLOR_PALETTE:
        if color.lower() not in used:
            return color
    return _unique_fallback(layer_name or "layer", used)


def enrich_layer_style(
    style: dict | None,
    layer_type: str,
    *,
    layer_name: str = "",
    preferred_hex: str | None = None,
    used_colors: list[str] | None = None,
    suggest_if_empty: bool = False,
) -> dict:
    style = dict(style or {})
    has_color = bool(style.get("fill") or style.get("stroke"))
    if suggest_if_empty and not has_color:
        hex_color = suggest_layer_hex(
            layer_name,
            used_colors=used_colors,
            preferred_hex=preferred_hex,
        )
    else:
        hex_color = style.get("fill") or style.get("stroke") or "#0D9488"
    hex_norm = normalize_hex(str(hex_color))
    style["fill"] = hex_norm
    style.setdefault("stroke", hex_norm)
    if style.get("strokeWidth") is None:
        style["strokeWidth"] = 1.5
    style.update(rgba_for_layer_type(hex_norm, layer_type))
    return style


def primary_hex_from_style(style: dict | None) -> str:
    style = style or {}
    for key in ("fill", "stroke"):
        value = style.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_hex(value)
    return "#0D9488"
