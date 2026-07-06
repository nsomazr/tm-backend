"""Common exploration / geological map colors (industry conventions + periodic-table cues)."""

from __future__ import annotations

from django.utils.text import slugify

# slug, aliases (lowercase), hex, short note
GEOLOGICAL_MINERAL_COLORS: list[dict] = [
    {"slug": "gold", "aliases": ["gold", "dhahabu", "au"], "hex": "#E87722", "note": "Precious metal: warm gold / amber"},
    {"slug": "silver", "aliases": ["silver", "fedha", "ag"], "hex": "#C0C0C0", "note": "Precious metal: silver gray"},
    {"slug": "copper", "aliases": ["copper", "shaba", "cu"], "hex": "#B87333", "note": "Base metal: copper brown"},
    {"slug": "iron-ore", "aliases": ["iron", "iron-ore", "iron ore", "fe", "magnetite", "hematite"], "hex": "#4A3728", "note": "Iron / BIF: dark rust brown"},
    {"slug": "nickel", "aliases": ["nickel", "ni"], "hex": "#708090", "note": "Base metal: blue-gray"},
    {"slug": "lithium", "aliases": ["lithium", "li", "spodumene"], "hex": "#00CED1", "note": "Battery metal: cyan"},
    {"slug": "graphite", "aliases": ["graphite", "carbon", "c"], "hex": "#2D2D2D", "note": "Industrial: charcoal"},
    {"slug": "diamond", "aliases": ["diamond", "almasi", "kimberlite"], "hex": "#BACE73", "note": "Gem: pale chartreuse"},
    {"slug": "tanzanite", "aliases": ["tanzanite", "zoisite"], "hex": "#7B2D8E", "note": "Gem: violet"},
    {"slug": "coal", "aliases": ["coal", "makaa"], "hex": "#1A1A1A", "note": "Energy: near black"},
    {"slug": "uranium", "aliases": ["uranium", "u"], "hex": "#32CD32", "note": "Radioactive: map green (USGS-style)"},
    {"slug": "tin", "aliases": ["tin", "sn", "cassiterite"], "hex": "#A8A8A8", "note": "Base metal: light gray"},
    {"slug": "tungsten", "aliases": ["tungsten", "w", "wolframite"], "hex": "#36454F", "note": "Critical metal: charcoal blue"},
    {"slug": "zinc", "aliases": ["zinc", "zn", "sphalerite"], "hex": "#7A8B8B", "note": "Base metal: blue-gray"},
    {"slug": "lead", "aliases": ["lead", "pb", "galena"], "hex": "#6B6B6B", "note": "Base metal: medium gray"},
    {"slug": "cobalt", "aliases": ["cobalt", "co"], "hex": "#0047AB", "note": "Battery metal: cobalt blue"},
    {"slug": "manganese", "aliases": ["manganese", "mn", "pyrolusite"], "hex": "#8B4513", "note": "Industrial: saddle brown"},
    {"slug": "bauxite", "aliases": ["bauxite", "aluminium", "aluminum", "al"], "hex": "#CD853F", "note": "Aluminum ore: sandy brown"},
    {"slug": "phosphate", "aliases": ["phosphate", "phosphorite", "p"], "hex": "#E07A5F", "note": "Fertilizer: coral"},
    {"slug": "limestone", "aliases": ["limestone", "lime", "caco3"], "hex": "#F5F5DC", "note": "Industrial: beige"},
    {"slug": "gypsum", "aliases": ["gypsum", "sulfate"], "hex": "#E8E4D9", "note": "Industrial: off-white"},
    {"slug": "salt", "aliases": ["salt", "chumvi", "halite"], "hex": "#F0F8FF", "note": "Evaporite: alice blue"},
    {"slug": "rare-earth", "aliases": ["rare earth", "ree", "neodymium"], "hex": "#9932CC", "note": "Critical minerals: dark orchid"},
    {"slug": "gemstone", "aliases": ["gem", "gemstone", "ruby", "sapphire", "emerald"], "hex": "#9B59B6", "note": "Colored gems: purple"},
    {"slug": "oil-gas", "aliases": ["oil", "gas", "petroleum", "hydrocarbon"], "hex": "#1C2833", "note": "Energy: midnight blue"},
    {"slug": "water", "aliases": ["water", "groundwater", "aquifer"], "hex": "#3498DB", "note": "Hydrogeology: blue"},
]


def match_geological_color(name: str) -> str | None:
    if not name:
        return None
    slug = slugify(name) or ""
    lower = name.lower()
    for entry in GEOLOGICAL_MINERAL_COLORS:
        if slug == entry["slug"]:
            return entry["hex"]
        for alias in entry["aliases"]:
            alias_slug = slugify(alias)
            if alias in lower or (alias_slug and alias_slug in slug):
                return entry["hex"]
    return None
