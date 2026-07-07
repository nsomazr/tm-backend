"""Rank districts and mapped zones by similarity to a clicked analysis area."""

from __future__ import annotations

import math
import re
from typing import Any

from django.core.cache import cache

from apps.geography.models import AdminBoundary
from apps.maps.localization import localized_name

from .insights import _accessible_feature_list
from .spatial_assign import commodities_from_features, features_in_boundary
from .terrain_context import build_terrain_context

PROFILE_CACHE_TTL = 60 * 60  # 1 hour
MAX_CANDIDATES = 6
TERRAIN_ENRICH_LIMIT = 18


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _geology_tokens(geological_context: dict | None) -> set[str]:
    if not geological_context:
        return set()
    tokens: set[str] = set()
    for entry in geological_context.get("entries") or []:
        for field in ("formations", "lithology", "stratigraphy", "tectonic_setting"):
            raw = entry.get(field) or ""
            for word in re.findall(r"[a-zA-Z]{4,}", str(raw).lower()):
                tokens.add(word)
        summary = entry.get("summary") or entry.get("geological_summary") or ""
        for word in re.findall(r"[a-zA-Z]{4,}", str(summary).lower()):
            tokens.add(word)
    return tokens


def fingerprint_from_context(ctx: dict) -> dict[str, Any]:
    mineral_slugs: set[str] = set()
    for row in ctx.get("minerals") or []:
        slug = row.get("slug")
        if slug:
            mineral_slugs.add(str(slug))
    terrain = ctx.get("terrain_context") or {}
    district = ctx.get("district_boundary") or {}
    return {
        "lat": float(ctx["lat"]),
        "lng": float(ctx["lng"]),
        "district_id": district.get("id"),
        "region": ctx.get("geographic_region") or ctx.get("region"),
        "mineral_slugs": mineral_slugs,
        "terrain": {
            "elevation_m": terrain.get("elevation_m"),
            "relief_m": terrain.get("relief_m"),
            "relief_class": terrain.get("relief_class"),
            "slope_class": terrain.get("slope_class"),
            "landform_hint": terrain.get("landform_hint"),
        },
        "geology_tokens": _geology_tokens(ctx.get("geological_context")),
    }


def _district_profiles(country_code: str, user, locale: str = "en") -> list[dict[str, Any]]:
    cache_key = f"similar-district-profiles:{country_code.upper()}:{getattr(user, 'id', 'anon')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    features = _accessible_feature_list(user, limit=8000)
    districts = (
        AdminBoundary.objects.filter(
            country__code=country_code.upper(),
            level=AdminBoundary.Level.DISTRICT,
        )
        .select_related("region", "parent")
        .only(
            "id",
            "name",
            "name_sw",
            "center_lat",
            "center_lng",
            "geological_summary",
            "geological_metadata",
            "region_id",
            "region__name",
            "parent_id",
            "parent__name",
        )
    )

    profiles: list[dict[str, Any]] = []
    for district in districts:
        lat = district.center_lat
        lng = district.center_lng
        if lat is None or lng is None:
            continue
        matched = features_in_boundary(district, features)
        if not matched:
            continue
        minerals = commodities_from_features(matched, locale=locale)
        slugs = {str(row.get("slug")) for row in minerals if row.get("slug")}
        if not slugs:
            continue
        region_name = None
        if district.region:
            region_name = district.region.name
        elif district.parent:
            region_name = district.parent.name
        geology_text = " ".join(
            filter(
                None,
                [
                    district.geological_summary or "",
                    str((district.geological_metadata or {}).get("lithology") or ""),
                    str((district.geological_metadata or {}).get("formations") or ""),
                ],
            )
        )
        profiles.append(
            {
                "boundary_id": district.id,
                "label": localized_name(district, locale),
                "region": region_name,
                "lat": float(lat),
                "lng": float(lng),
                "mineral_slugs": slugs,
                "mineral_names": [row.get("name") for row in minerals[:4] if row.get("name")],
                "feature_count": len(matched),
                "geology_tokens": {
                    word
                    for word in re.findall(r"[a-zA-Z]{4,}", geology_text.lower())
                },
                "terrain": None,
            }
        )

    cache.set(cache_key, profiles, PROFILE_CACHE_TTL)
    return profiles


def _terrain_similarity(source: dict, candidate: dict) -> float:
    src = source.get("terrain") or {}
    cand = candidate.get("terrain") or {}
    if src.get("elevation_m") is None or cand.get("elevation_m") is None:
        return 0.45

    elev_diff = abs(float(src["elevation_m"]) - float(cand["elevation_m"]))
    relief_diff = abs(float(src.get("relief_m") or 0) - float(cand.get("relief_m") or 0))
    score = max(0.0, 1.0 - elev_diff / 1800.0) * 0.55
    score += max(0.0, 1.0 - relief_diff / 350.0) * 0.25
    if src.get("slope_class") and src.get("slope_class") == cand.get("slope_class"):
        score += 0.12
    if src.get("relief_class") and src.get("relief_class") == cand.get("relief_class"):
        score += 0.08
    if src.get("landform_hint") and src.get("landform_hint") == cand.get("landform_hint"):
        score += 0.1
    return min(1.0, score)


def _match_reasons(
    source: dict,
    candidate: dict,
    *,
    locale: str = "en",
) -> list[str]:
    reasons: list[str] = []
    overlap = source.get("mineral_slugs", set()) & candidate.get("mineral_slugs", set())
    if overlap:
        names = ", ".join(sorted(overlap)[:3])
        if locale == "sw":
            reasons.append(f"Madini yanayolingana: {names}")
        else:
            reasons.append(f"Shared minerals: {names}")

    src_t = source.get("terrain") or {}
    cand_t = candidate.get("terrain") or {}
    if (
        src_t.get("landform_hint")
        and cand_t.get("landform_hint")
        and src_t["landform_hint"] == cand_t["landform_hint"]
    ):
        if locale == "sw":
            reasons.append(f"Mandhari sawa: {src_t['landform_hint']}")
        else:
            reasons.append(f"Similar landform: {src_t['landform_hint']}")
    elif src_t.get("relief_class") and src_t.get("relief_class") == cand_t.get("relief_class"):
        if locale == "sw":
            reasons.append(f"Mwinuko sawa ({src_t['relief_class']})")
        else:
            reasons.append(f"Similar relief ({src_t['relief_class']})")

    if source.get("region") and source.get("region") == candidate.get("region"):
        if locale == "sw":
            reasons.append(f"Mkoa sawa: {source['region']}")
        else:
            reasons.append(f"Same region: {source['region']}")

    geo_overlap = source.get("geology_tokens", set()) & candidate.get("geology_tokens", set())
    if geo_overlap:
        if locale == "sw":
            reasons.append("Muktadha wa kijiolojia unaofanana")
        else:
            reasons.append("Overlapping geological reference")

    if not reasons:
        if locale == "sw":
            reasons.append("Maeneo yaliyopangwa na mazingira yanayofanana")
        else:
            reasons.append("Comparable mapped setting")
    return reasons[:3]


def _score_candidate(source: dict, candidate: dict) -> float:
    mineral_score = _jaccard(source.get("mineral_slugs", set()), candidate.get("mineral_slugs", set()))
    terrain_score = _terrain_similarity(source, candidate)
    region_score = (
        1.0
        if source.get("region") and source.get("region") == candidate.get("region")
        else 0.0
    )
    geology_score = _jaccard(
        source.get("geology_tokens", set()),
        candidate.get("geology_tokens", set()),
    )
    return (
        mineral_score * 0.45
        + terrain_score * 0.30
        + region_score * 0.10
        + geology_score * 0.15
    )


def find_similar_areas(
    ctx: dict,
    user,
    *,
    locale: str = "en",
    limit: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Return ranked areas with similar minerals, terrain, and geology."""
    if not ctx.get("has_mapped_data"):
        return []

    source = fingerprint_from_context(ctx)
    country_code = (ctx.get("country_code") or "TZ").upper()
    profiles = _district_profiles(country_code, user, locale=locale)
    if not profiles:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for profile in profiles:
        if source.get("district_id") and profile.get("boundary_id") == source.get("district_id"):
            continue
        if _haversine_km(source["lat"], source["lng"], profile["lat"], profile["lng"]) < 8:
            continue
        rough = _score_candidate(source, profile)
        if rough < 0.12:
            continue
        scored.append((rough, profile))

    scored.sort(key=lambda row: row[0], reverse=True)
    shortlist = [profile for _, profile in scored[:TERRAIN_ENRICH_LIMIT]]

    analysis_km2 = ctx.get("analysis_area_km2")
    for profile in shortlist:
        if profile.get("terrain"):
            continue
        terrain = build_terrain_context(
            profile["lat"],
            profile["lng"],
            analysis_area_km2=analysis_km2,
            locale=locale,
        )
        if terrain:
            profile["terrain"] = {
                "elevation_m": terrain.get("elevation_m"),
                "relief_m": terrain.get("relief_m"),
                "relief_class": terrain.get("relief_class"),
                "slope_class": terrain.get("slope_class"),
                "landform_hint": terrain.get("landform_hint"),
            }

    rescored: list[tuple[float, dict[str, Any]]] = []
    for profile in shortlist:
        score = _score_candidate(source, profile)
        if score < 0.15:
            continue
        rescored.append((score, profile))
    rescored.sort(key=lambda row: row[0], reverse=True)

    results: list[dict[str, Any]] = []
    for score, profile in rescored[:limit]:
        results.append(
            {
                "boundary_id": profile["boundary_id"],
                "label": profile["label"],
                "region": profile.get("region"),
                "lat": profile["lat"],
                "lng": profile["lng"],
                "score": round(score * 100),
                "minerals": profile.get("mineral_names") or [],
                "feature_count": profile.get("feature_count") or 0,
                "match_reasons": _match_reasons(source, profile, locale=locale),
                "terrain_hint": (profile.get("terrain") or {}).get("landform_hint"),
            }
        )
    return results
