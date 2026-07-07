"""Basemap labels and AI interpretation hints (mirrors frontend basemaps.ts)."""

VALID_BASEMAPS = frozenset({"streets", "light", "dark", "satellite", "terrain", "topo"})
TERRAIN_VISUAL_BASEMAPS = frozenset({"satellite", "terrain", "topo"})

_BASEMAP_META: dict[str, dict[str, str]] = {
    "streets": {
        "label": "Streets",
        "description": "OpenStreetMap roads & labels",
        "hint_en": (
            "The user is viewing a street map. When relevant, mention road access, "
            "settlement proximity, and infrastructure for exploration logistics."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia ramani ya barabara. Eleza upatikanaji wa barabara, "
            "makazi karibu, na miundombinu ya uchunguzi inapohitajika."
        ),
    },
    "light": {
        "label": "Light",
        "description": "Clean minimal base",
        "hint_en": (
            "The user is viewing a minimal light basemap. Focus on mapped mineral data "
            "and administrative context rather than surface landform interpretation."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia ramani nyepesi ya msingi. Zingatia data ya madini "
            "iliyopangwa na muktadha wa utawala badala ya maumbo ya uso wa ardhi."
        ),
    },
    "dark": {
        "label": "Dark",
        "description": "Night-style base",
        "hint_en": (
            "The user is viewing a dark basemap. Focus on mapped mineral data "
            "and administrative context rather than surface landform interpretation."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia ramani ya giza. Zingatia data ya madini iliyopangwa "
            "na muktadha wa utawala."
        ),
    },
    "satellite": {
        "label": "Satellite",
        "description": "Esri world imagery",
        "hint_en": (
            "The user is viewing satellite imagery. Describe visible land cover, drainage "
            "patterns, lineaments, and exposed rock only when supported by the image or "
            "terrain data. Do not invent basin names or deposit types."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia picha za satelaiti. Eleza ufunuo wa ardhi, mifereji ya maji, "
            "na miamba iliyo wazi tu inapothibitishwa na picha au data ya mwinuko."
        ),
    },
    "terrain": {
        "label": "Terrain",
        "description": "Hillshade & elevation",
        "hint_en": (
            "The user is viewing a terrain hillshade basemap. Emphasize relief, ridges, "
            "valleys, and drainage when terrain metrics are provided. Relate landform "
            "character to exploration access and structural setting cautiously."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia ramani ya mwinuko na vivuli. Eleza mwinuko, vilele, "
            "mabonde, na mifereji ya maji pale data ya mwinuko inapotolewa."
        ),
    },
    "topo": {
        "label": "Topo labels",
        "description": "Imagery + place names",
        "hint_en": (
            "The user is viewing satellite imagery with place-name labels. Combine land-cover "
            "and relief interpretation with named settlements and geographic features visible "
            "on the map view."
        ),
        "hint_sw": (
            "Mtumiaji anaangalia picha za satelaiti na majina ya maeneo. Changanya tafsiri "
            "ya ufunuo wa ardhi na majina ya makazi yanayoonekana kwenye ramani."
        ),
    },
}


def normalize_basemap(raw: str | None) -> str | None:
    if not raw:
        return None
    token = str(raw).strip().lower()
    return token if token in VALID_BASEMAPS else None


def is_terrain_visual_basemap(basemap: str | None) -> bool:
    return normalize_basemap(basemap) in TERRAIN_VISUAL_BASEMAPS


def basemap_label(basemap: str | None, locale: str = "en") -> str | None:
    meta = _BASEMAP_META.get(normalize_basemap(basemap) or "")
    return meta.get("label") if meta else None


def basemap_ai_block(basemap: str | None, locale: str = "en") -> str:
    bid = normalize_basemap(basemap)
    if not bid:
        return ""
    meta = _BASEMAP_META[bid]
    hint = meta.get("hint_sw" if locale == "sw" else "hint_en", "")
    return (
        f"Map view: {meta['label']} ({meta['description']}).\n"
        f"{hint}\n"
    )
