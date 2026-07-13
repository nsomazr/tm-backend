"""Valid map coordinate reference systems (synced with frontend catalog)."""

from __future__ import annotations

import re

DEFAULT_COORDINATE_SYSTEM = "wgs84"

# Static catalog ids (≤ 32 chars). WGS84 UTM zones use wgs84-utm{N}n|s.
VALID_COORDINATE_SYSTEMS = frozenset(
    {
        "wgs84",
        "webmercator",
        "arc1960",
        "arc1960-utm35s",
        "arc1960-utm36s",
        "arc1960-utm37s",
        "adindan",
        "hartebeesthoek94",
        "cape",
        "minna",
        "accra",
        "egypt1907",
        "merchich",
        "carthage",
        "etrs89",
        "osgb36",
        "pulkovo42",
        "nad83",
        "nad27",
        "sirgas2000",
        "psad56",
        "cgcs2000",
        "tokyo",
        "jgd2011",
        "kalianpur77",
        "gda94",
        "gda2020",
        "nzgd2000",
    }
)

_WGS84_UTM_RE = re.compile(r"^wgs84-utm([1-9]|[1-5][0-9]|60)[ns]$", re.IGNORECASE)

COUNTRY_DEFAULT_CRS = {
    "TZ": "arc1960",
    "KE": "arc1960",
    "UG": "arc1960",
    "RW": "arc1960-utm35s",
    "BI": "arc1960-utm35s",
    "ET": "adindan",
    "SD": "adindan",
    "ER": "adindan",
    "ZA": "hartebeesthoek94",
    "NA": "hartebeesthoek94",
    "BW": "hartebeesthoek94",
    "LS": "hartebeesthoek94",
    "SZ": "hartebeesthoek94",
    "ZW": "cape",
    "NG": "minna",
    "GH": "accra",
    "EG": "egypt1907",
    "MA": "merchich",
    "TN": "carthage",
    "GB": "osgb36",
    "US": "nad83",
    "CA": "nad83",
    "MX": "nad83",
    "BR": "sirgas2000",
    "AR": "sirgas2000",
    "CL": "sirgas2000",
    "CO": "sirgas2000",
    "PE": "sirgas2000",
    "CN": "cgcs2000",
    "JP": "jgd2011",
    "IN": "kalianpur77",
    "AU": "gda2020",
    "NZ": "nzgd2000",
    "RU": "pulkovo42",
    "DE": "etrs89",
    "FR": "etrs89",
    "ES": "etrs89",
    "IT": "etrs89",
    "NL": "etrs89",
}


def is_valid_coordinate_system(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value in VALID_COORDINATE_SYSTEMS:
        return True
    return bool(_WGS84_UTM_RE.match(value))


def default_coordinate_system_for_country(country_code: str) -> str:
    return COUNTRY_DEFAULT_CRS.get((country_code or "").upper(), DEFAULT_COORDINATE_SYSTEM)
