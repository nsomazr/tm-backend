"""Map mineral / layer slugs to periodic-table element positions."""

from __future__ import annotations

# Gemstones and non-element commodities shown below the actinide row.
SPECIAL_PERIODIC_SLUGS: frozenset[str] = frozenset({"tanzanite", "diamond"})

# First matching keyword wins (most specific patterns first).
_SLUG_KEYWORDS_TO_Z: tuple[tuple[tuple[str, ...], int], ...] = (
    (("lithium",), 3),
    (("graphite", "coal"), 6),
    (("beryllium",), 4),
    (("boron",), 5),
    (("magnesium",), 12),
    (("aluminum", "aluminium", "bauxite"), 13),
    (("silicon",), 14),
    (("phosphate", "phosphorus"), 15),
    (("sulfur", "sulphur"), 16),
    (("potash", "potassium", "sylvite"), 19),
    (("titanium",), 22),
    (("vanadium",), 23),
    (("chromium",), 24),
    (("manganese",), 25),
    (("iron", "iron-ore"), 26),
    (("cobalt",), 27),
    (("nickel",), 28),
    (("copper",), 29),
    (("zinc",), 30),
    (("gallium",), 31),
    (("germanium",), 32),
    (("arsenic",), 33),
    (("selenium",), 34),
    (("silver",), 47),
    (("tin",), 50),
    (("antimony",), 51),
    (("tellurium",), 52),
    (("cesium", "caesium"), 55),
    (("barium",), 56),
    (("lanthanum", "rare-earth", "ree", "neodymium"), 57),
    (("hafnium",), 72),
    (("tantalum",), 73),
    (("tungsten",), 74),
    (("rhenium",), 75),
    (("osmium",), 76),
    (("iridium",), 77),
    (("platinum",), 78),
    (("gold",), 79),
    (("mercury",), 80),
    (("lead",), 82),
    (("bismuth",), 83),
    (("thorium",), 90),
    (("uranium",), 92),
)


def resolve_periodic_z(slug: str) -> int | None:
    if not slug or slug == "general":
        return None
    if slug in SPECIAL_PERIODIC_SLUGS:
        return None
    normalized = slug.lower().replace("_", "-")
    for keywords, z in _SLUG_KEYWORDS_TO_Z:
        if any(kw in normalized for kw in keywords):
            return z
    return None


def resolve_periodic_special(slug: str) -> str | None:
    if slug in SPECIAL_PERIODIC_SLUGS:
        return slug
    return None
