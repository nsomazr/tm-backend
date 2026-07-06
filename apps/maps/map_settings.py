DEFAULT_COORDINATE_SYSTEM = "arc1960"

VALID_COORDINATE_SYSTEMS = frozenset(
    {
        "arc1960",
        "arc1960-utm35s",
        "arc1960-utm36s",
        "arc1960-utm37s",
        "wgs84",
        "webmercator",
    }
)


def is_valid_coordinate_system(value: str) -> bool:
    return value in VALID_COORDINATE_SYSTEMS
