"""Convert ESRI Shapefiles to GeoJSON-like feature dicts using pyshp."""

from __future__ import annotations

import io
import json
import os
import struct
import tempfile
import zipfile
from typing import Any

import shapefile

from .crs_utils import ensure_wgs84_geometry
from .upload_security import (
    UploadValidationError,
    friendly_upload_error,
    validate_feature_count,
    validate_upload_bytes,
    validate_zip_archive,
)


def detect_file_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".shp"):
        return "shapefile"
    if lower.endswith(".geojson"):
        return "geojson"
    if lower.endswith(".json"):
        return "json"
    return "geojson"


def parse_upload_content(
    content: bytes,
    filename: str,
    file_type: str | None = None,
    *,
    boundary: bool = False,
) -> list[dict[str, Any]]:
    ft = file_type or detect_file_type(filename)
    try:
        validate_upload_bytes(content, filename, boundary=boundary)
        if ft == "shapefile" or filename.lower().endswith(".shp"):
            features = shapefile_bytes_to_features(content)
        elif ft == "zip" or filename.lower().endswith(".zip"):
            features = _parse_zip(content)
        else:
            data = _load_json_bytes(content)
            features = _normalize_features(data)
        validate_feature_count(len(features), boundary=boundary)
        return features
    except UploadValidationError as exc:
        raise ValueError(str(exc)) from exc
    except (ValueError, json.JSONDecodeError, struct.error, shapefile.ShapefileException, OSError, UnicodeDecodeError, TypeError) as exc:
        raise ValueError(friendly_upload_error(exc)) from exc


def _load_json_bytes(content: bytes) -> dict[str, Any]:
    text = content.decode("utf-8-sig").strip()
    decoder = json.JSONDecoder()
    data, _idx = decoder.raw_decode(text)
    if not isinstance(data, dict):
        raise ValueError("Invalid GeoJSON: expected a JSON object.")
    return data


def _is_mac_junk(name: str) -> bool:
    lower = name.lower()
    if lower.startswith("__macosx/"):
        return True
    basename = name.rsplit("/", 1)[-1]
    return basename.startswith("._")


def _is_valid_shp_entry(name: str) -> bool:
    if not name.lower().endswith(".shp"):
        return False
    return not _is_mac_junk(name)


def _parse_zip(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        validate_zip_archive(zf, len(content))
        names = zf.namelist()
        for name in names:
            if _is_mac_junk(name):
                continue
            if name.lower().endswith((".geojson", ".json")):
                return _normalize_features(_load_json_bytes(zf.read(name)))
        shp_names = [n for n in names if _is_valid_shp_entry(n)]
        errors: list[str] = []
        for shp_name in sorted(shp_names, key=lambda n: zf.getinfo(n).file_size, reverse=True):
            try:
                return _shapefile_from_zip(zf, shp_name)
            except ValueError as exc:
                errors.append(f"{shp_name.rsplit('/', 1)[-1]}: {exc}")
            except (struct.error, shapefile.ShapefileException) as exc:
                errors.append(f"{shp_name.rsplit('/', 1)[-1]}: {exc}")
        if shp_names and errors:
            raise ValueError(
                "No readable shapefile found in ZIP. " + "; ".join(errors[:2])
            )
    raise ValueError("ZIP must contain a .shp set (.shp + .shx + .dbf) or a GeoJSON file.")


def _collect_shapefile_parts(zf: zipfile.ZipFile, shp_name: str) -> dict[str, bytes]:
    """Find companion files (any letter case) in the same ZIP folder."""
    directory = shp_name.rpartition("/")[0]
    stem = shp_name.rsplit("/", 1)[-1][:-4].lower()
    parts: dict[str, bytes] = {}

    for name in zf.namelist():
        if _is_mac_junk(name):
            continue
        name_dir = name.rpartition("/")[0]
        if directory:
            if name_dir != directory:
                continue
        elif "/" in name:
            continue
        base = name.rsplit("/", 1)[-1]
        if "." not in base:
            continue
        file_stem, ext = base.rsplit(".", 1)
        if file_stem.lower() != stem:
            continue
        parts[f".{ext.lower()}"] = zf.read(name)

    return parts


def _valid_shp_header(data: bytes) -> bool:
    return len(data) >= 100 and data[0:4] == b"\x00\x00\x27\x0a"


def _valid_shx_header(data: bytes) -> bool:
    return len(data) >= 100 and data[0:4] == b"\x00\x00\x27\x0a"


def _valid_dbf_header(data: bytes) -> bool:
    """dBASE / FoxPro DBF version byte."""
    if len(data) < 32:
        return False
    return data[0] in (
        0x02,
        0x03,
        0x04,
        0x05,
        0x07,
        0x30,
        0x31,
        0x32,
        0x83,
        0x8B,
        0x8C,
        0xF5,
    )


def _shapefile_reader_from_parts(parts: dict[str, bytes]) -> shapefile.Reader:
    shp = parts[".shp"]
    shx = parts.get(".shx")
    dbf = parts.get(".dbf")

    use_shx = bool(shx and _valid_shx_header(shx))
    use_dbf = bool(dbf and _valid_dbf_header(dbf))

    shp_io = io.BytesIO(shp)
    shx_io = io.BytesIO(shx) if use_shx else None
    dbf_io = io.BytesIO(dbf) if use_dbf else None

    if shx_io and dbf_io:
        for encoding in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
            try:
                return shapefile.Reader(
                    shp=io.BytesIO(shp),
                    shx=io.BytesIO(shx),
                    dbf=io.BytesIO(dbf),
                    encoding=encoding,
                )
            except UnicodeDecodeError:
                continue
        return shapefile.Reader(shp=io.BytesIO(shp), shx=io.BytesIO(shx), dbf=io.BytesIO(dbf))

    if shx_io:
        return shapefile.Reader(shp=io.BytesIO(shp), shx=io.BytesIO(shx))

    return shapefile.Reader(shp=io.BytesIO(shp))


def _shapefile_from_zip(zf: zipfile.ZipFile, shp_name: str) -> list[dict[str, Any]]:
    parts = _collect_shapefile_parts(zf, shp_name)

    if ".shp" not in parts:
        raise ValueError("missing .shp file")
    if not _valid_shp_header(parts[".shp"]):
        raise ValueError(".shp file is empty or invalid")

    reader = _shapefile_reader_from_parts(parts)
    prj = parts.get(".prj")
    source_wkt = prj.decode("utf-8", errors="replace") if prj else None
    return _features_from_reader(reader, source_wkt=source_wkt)


def shapefile_bytes_to_features(
    shp_bytes: bytes,
    shx_bytes: bytes | None = None,
    dbf_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    parts: dict[str, bytes] = {".shp": shp_bytes}
    if shx_bytes:
        parts[".shx"] = shx_bytes
    if dbf_bytes:
        parts[".dbf"] = dbf_bytes
    reader = _shapefile_reader_from_parts(parts)
    return _features_from_reader(reader)


def _features_from_reader(
    reader: shapefile.Reader,
    *,
    source_wkt: str | None = None,
) -> list[dict[str, Any]]:
    field_names = [f[0] for f in reader.fields[1:]]
    has_attributes = bool(field_names)
    features: list[dict[str, Any]] = []

    try:
        count = reader.numRecords
    except Exception:
        count = None
    if not count:
        count = len(reader.shapes())

    for i in range(count):
        try:
            shape = reader.shape(i)
            record = reader.record(i) if has_attributes else []
        except (struct.error, shapefile.ShapefileException, IndexError, UnicodeDecodeError):
            continue
        geom = _shape_to_geojson(shape)
        if not geom:
            continue
        geom = ensure_wgs84_geometry(geom, source_wkt=source_wkt)
        if not geom:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": _record_to_props(list(record), field_names),
            }
        )

    if not features:
        raise ValueError("Shapefile contains no readable polygon/line/point features.")
    return features


def _record_to_props(record: list[Any], field_names: list[str]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for i, name in enumerate(field_names):
        if i >= len(record):
            break
        val = record[i]
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="replace")
        props[name] = val
    return props



def _shape_to_geojson(shape: shapefile.Shape) -> dict[str, Any] | None:
    st = shape.shapeType
    parts = list(shape.parts) + [len(shape.points)]

    if st in (shapefile.POINT, shapefile.POINTZ, shapefile.POINTM):
        if not shape.points:
            return None
        x, y = shape.points[0]
        return {"type": "Point", "coordinates": [x, y]}

    if st in (shapefile.POLYLINE, shapefile.POLYLINEZ, shapefile.POLYLINEM):
        lines = []
        for i in range(len(shape.parts)):
            start = shape.parts[i]
            end = parts[i + 1]
            lines.append([[p[0], p[1]] for p in shape.points[start:end]])
        if len(lines) == 1:
            return {"type": "LineString", "coordinates": lines[0]}
        return {"type": "MultiLineString", "coordinates": lines}

    if st in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
        rings = []
        for i in range(len(shape.parts)):
            start = shape.parts[i]
            end = parts[i + 1]
            ring = [[p[0], p[1]] for p in shape.points[start:end]]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            rings.append(ring)
        if len(rings) == 1:
            return {"type": "Polygon", "coordinates": rings}
        return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}

    return None


def _normalize_features(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("type") == "FeatureCollection":
        return data.get("features", [])
    if data.get("type") == "Feature":
        return [data]
    raise ValueError("Invalid GeoJSON: expected FeatureCollection or Feature.")


def write_polygon_shapefile_zip(
    features: list[dict[str, Any]],
    out_path: str,
) -> None:
    """Write polygon features (with properties name, region) to a shapefile zip."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "layer")
        w = shapefile.Writer(base, shapeType=shapefile.POLYGON)
        w.field("name", "C", 80)
        w.field("region", "C", 40)
        w.field("mineral", "C", 40)

        for feat in features:
            geom = feat["geometry"]
            props = feat.get("properties", {})
            rings = _polygon_rings(geom)
            if not rings:
                continue
            w.poly(rings)
            w.record(
                props.get("name", ""),
                props.get("region", ""),
                props.get("mineral", ""),
            )
        w.close()

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for ext in (".shp", ".shx", ".dbf", ".prj"):
                fp = base + ext
                if os.path.exists(fp):
                    zf.write(fp, f"layer{ext}")


def write_line_shapefile_zip(features: list[dict[str, Any]], out_path: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "layer")
        w = shapefile.Writer(base, shapeType=shapefile.POLYLINE)
        w.field("name", "C", 80)
        w.field("region", "C", 40)

        for feat in features:
            geom = feat["geometry"]
            coords = geom.get("coordinates", [])
            if geom.get("type") == "LineString":
                w.line([coords])
            elif geom.get("type") == "MultiLineString":
                w.line(coords)
            props = feat.get("properties", {})
            w.record(props.get("name", ""), props.get("region", ""))
        w.close()

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for ext in (".shp", ".shx", ".dbf"):
                fp = base + ext
                if os.path.exists(fp):
                    zf.write(fp, f"layer{ext}")


def _polygon_rings(geom: dict[str, Any]) -> list[list[list[float]]]:
    gtype = geom.get("type")
    coords = geom.get("coordinates", [])
    if gtype == "Polygon":
        return [coords[0]]
    if gtype == "MultiPolygon":
        return [poly[0] for poly in coords]
    return []
