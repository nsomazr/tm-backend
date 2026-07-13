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
    {"slug": "graphite", "aliases": ["graphite", "carbon"], "hex": "#2D2D2D", "note": "Industrial: charcoal"},
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
    {"slug": "phosphate", "aliases": ["phosphate", "phosphorite"], "hex": "#E07A5F", "note": "Fertilizer: coral"},
    {"slug": "limestone", "aliases": ["limestone", "lime"], "hex": "#F5F5DC", "note": "Industrial: beige"},
    {"slug": "gypsum", "aliases": ["gypsum", "sulfate"], "hex": "#E8E4D9", "note": "Industrial: off-white"},
    {"slug": "salt", "aliases": ["salt", "chumvi", "halite"], "hex": "#F0F8FF", "note": "Evaporite: alice blue"},
    {"slug": "rare-earth", "aliases": ["rare earth", "ree", "neodymium"], "hex": "#9932CC", "note": "Critical minerals: dark orchid"},
    {"slug": "gemstone", "aliases": ["gem", "gemstone"], "hex": "#9B59B6", "note": "Colored gems: purple"},
    {"slug": "oil-gas", "aliases": ["oil", "gas", "petroleum", "hydrocarbon"], "hex": "#1C2833", "note": "Energy: midnight blue"},
    {"slug": "water", "aliases": ["water", "groundwater", "aquifer"], "hex": "#3498DB", "note": "Hydrogeology: blue"},
    {"slug": "vanadium", "aliases": ["vanadium", "v", "vanadinite"], "hex": "#4169E1", "note": "Battery metal: royal blue"},
    {"slug": "platinum", "aliases": ["platinum", "pt", "pgm"], "hex": "#E5E4E2", "note": "Precious / PGM: platinum gray"},
    {"slug": "palladium", "aliases": ["palladium", "pd"], "hex": "#CED0DD", "note": "Precious / PGM: pale silver"},
    {"slug": "chromium", "aliases": ["chromium", "cr", "chromite"], "hex": "#5C4033", "note": "Critical metal: chromite brown"},
    {"slug": "molybdenum", "aliases": ["molybdenum", "mo", "molybdenite"], "hex": "#778899", "note": "Base metal: light slate"},
    {"slug": "titanium", "aliases": ["titanium", "ti", "ilmenite", "rutile"], "hex": "#878681", "note": "Industrial: titanium gray"},
    {"slug": "tantalum", "aliases": ["tantalum", "ta", "coltan"], "hex": "#4B0082", "note": "Critical metal: indigo"},
    {"slug": "niobium", "aliases": ["niobium", "nb", "columbite"], "hex": "#7B68EE", "note": "Critical metal: medium slate blue"},
    {"slug": "antimony", "aliases": ["antimony", "sb", "stibnite"], "hex": "#9FA096", "note": "Industrial: gray-green"},
    {"slug": "zircon", "aliases": ["zircon", "zr", "zircon sand"], "hex": "#D4AF37", "note": "Industrial: golden sand"},
    {"slug": "thorium", "aliases": ["thorium", "th"], "hex": "#FF4500", "note": "Radioactive: orange-red"},
    {"slug": "potash", "aliases": ["potash", "sylvite"], "hex": "#FF6B35", "note": "Fertilizer: orange"},
    {"slug": "sulfur", "aliases": ["sulfur", "sulphur"], "hex": "#D4C430", "note": "Industrial: sulfur yellow"},
    {"slug": "fluorspar", "aliases": ["fluorspar", "fluorite", "fluorine"], "hex": "#9966CC", "note": "Industrial: amethyst purple"},
    {"slug": "kaolin", "aliases": ["kaolin", "clay", "china clay"], "hex": "#F4E4BC", "note": "Industrial: pale clay"},
    {"slug": "sand-gravel", "aliases": ["sand", "gravel", "aggregate"], "hex": "#C2B280", "note": "Construction: sand tan"},
    {"slug": "peat", "aliases": ["peat", "tourbe"], "hex": "#3D2817", "note": "Energy: dark peat"},
    {"slug": "geothermal", "aliases": ["geothermal", "geothermal energy"], "hex": "#E25822", "note": "Energy: flame orange"},
    {"slug": "ruby", "aliases": ["ruby"], "hex": "#E0115F", "note": "Gem: ruby red"},
    {"slug": "sapphire", "aliases": ["sapphire"], "hex": "#0F52BA", "note": "Gem: sapphire blue"},
    {"slug": "emerald", "aliases": ["emerald"], "hex": "#50C878", "note": "Gem: emerald green"},
    {"slug": "mercury", "aliases": ["mercury", "hg", "cinnabar"], "hex": "#A9A9A9", "note": "Hazardous: dark silver"},
    {"slug": "natural-gas", "aliases": ["natural gas", "lng", "lpg"], "hex": "#4A5568", "note": "Energy: blue-gray"},
]


def match_geological_color(name: str) -> str | None:
    if not name:
        return None
    import re

    slug = slugify(name) or ""
    lower = name.lower()
    tokens = [t for t in slug.split("-") if t]
    raw_tokens = [t for t in re.split(r"[^a-z0-9]+", lower) if t]

    for entry in GEOLOGICAL_MINERAL_COLORS:
        if slug == entry["slug"]:
            return entry["hex"]

    for entry in GEOLOGICAL_MINERAL_COLORS:
        for alias in entry["aliases"]:
            alias_lower = alias.lower()
            alias_slug = slugify(alias)
            if len(alias_lower) <= 2:
                if alias_lower in raw_tokens or alias_lower in tokens:
                    return entry["hex"]
                continue
            if alias_lower in lower or (alias_slug and alias_slug in slug):
                return entry["hex"]
    return None
