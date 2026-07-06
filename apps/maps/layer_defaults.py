from django.utils.text import slugify

from apps.geography.models import Country
from apps.minerals.color_utils import hex_to_rgba
from apps.minerals.geological_colors import match_geological_color
from apps.minerals.models import Mineral

GENERAL_MINERAL_SLUG = "general"


def get_or_create_mineral_for_layer(name: str, *, country=None) -> Mineral:
    """Ensure each commodity layer is linked to a distinct mineral record."""
    slug = slugify(name) or GENERAL_MINERAL_SLUG
    if slug == GENERAL_MINERAL_SLUG:
        return get_or_create_general_mineral()
    if country is None:
        country = Country.objects.filter(code="TZ").first()
    matched = match_geological_color(name)
    default_color = matched or "#0D9488"
    mineral, _ = Mineral.objects.get_or_create(
        slug=slug,
        defaults={
            "name": name.strip() or slug.replace("-", " ").title(),
            "country": country,
            "color": default_color,
            "color_rgba": hex_to_rgba(default_color, 0.55),
            "description": f"Commodity layer: {name.strip()}",
        },
    )
    if country and mineral.country_id != country.id:
        mineral.country = country
        mineral.save(update_fields=["country"])
    return mineral


def get_or_create_general_mineral() -> Mineral:
    country = Country.objects.filter(code="TZ").first()
    mineral, _ = Mineral.objects.get_or_create(
        slug=GENERAL_MINERAL_SLUG,
        defaults={
            "name": "General",
            "name_sw": "Jumla",
            "country": country,
            "color": "#64748B",
            "color_rgba": hex_to_rgba("#64748B", 0.55),
            "description": "Default grouping for map layers",
        },
    )
    if country and mineral.country_id != country.id:
        mineral.country = country
        mineral.save(update_fields=["country"])
    return mineral


def sync_mineral_color_from_layer(mineral: Mineral, style: dict, layer_type: str) -> None:
    from apps.minerals.color_utils import enrich_layer_style, primary_hex_from_style

    enriched = enrich_layer_style(style, layer_type)
    hex_color = primary_hex_from_style(enriched)
    fill_rgba = enriched.get("fillRgba") or hex_to_rgba(hex_color, 0.55)
    if mineral.color != hex_color or mineral.color_rgba != fill_rgba:
        mineral.color = hex_color
        mineral.color_rgba = fill_rgba
        mineral.save(update_fields=["color", "color_rgba"])
