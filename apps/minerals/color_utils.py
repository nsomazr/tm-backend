import re

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


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


def enrich_layer_style(style: dict | None, layer_type: str) -> dict:
    style = dict(style or {})
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
