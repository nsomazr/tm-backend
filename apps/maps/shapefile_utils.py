"""Convert ESRI Shapefiles to GeoJSON-like feature dicts using pyshp."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import shapefile


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


def parse_upload_content(content: bytes, filename: str, file_type: str | None = None) -> list[dict[str, Any]]:
    ft = file_type or detect_file_type(filename)
    if ft == "shapefile" or filename.lower().endswith(".shp"):
        return shapefile_bytes_to_features(content)
    if ft == "zip" or filename.lower().endswith(".zip"):
        return _parse_zip(content)
    data = json.loads(content)
    return _normalize_features(data)


def _parse_zip(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        shp_names = [n for n in names if n.lower().endswith(".shp")]
        if shp_names:
            return _shapefile_from_zip(zf, shp_names[0])
        for name in names:
            if name.lower().endswith((".geojson", ".json")):
                return _normalize_features(json.loads(zf.read(name)))
    raise ValueError("ZIP must contain a .shp set or GeoJSON file.")


def _shapefile_from_zip(zf: zipfile.ZipFile, shp_name: str) -> list[dict[str, Any]]:
    base = shp_name[:-4]
    parts = {}
    for ext in (".shp", ".shx", ".dbf", ".prj"):
        candidate = base + ext
        match = next((n for n in zf.namelist() if n.lower() == candidate.lower()), None)
        if match:
            parts[ext] = zf.read(match)
    if ".shp" not in parts or ".shx" not in parts:
        raise ValueError("Shapefile ZIP requires at least .shp and .shx files.")
    return shapefile_bytes_to_features(parts[".shp"], parts.get(".shx"), parts.get(".dbf"))


def shapefile_bytes_to_features(
    shp_bytes: bytes,
    shx_bytes: bytes | None = None,
    dbf_bytes: bytes | None = None,
) -> list[dict[str, Any]]:
    if shx_bytes and dbf_bytes:
        reader = shapefile.Reader(
            shp=io.BytesIO(shp_bytes),
            shx=io.BytesIO(shx_bytes),
            dbf=io.BytesIO(dbf_bytes),
        )
    else:
        reader = shapefile.Reader(shp=io.BytesIO(shp_bytes))

    field_names = [f[0] for f in reader.fields[1:]]
    features: list[dict[str, Any]] = []

    for shape_rec in reader.iterShapeRecords():
        geom = _shape_to_geojson(shape_rec.shape)
        if not geom:
            continue
        props = {}
        for i, name in enumerate(field_names):
            val = shape_rec.record[i]
            if isinstance(val, bytes):
                val = val.decode("utf-8", errors="replace")
            props[name] = val
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    if not features:
        raise ValueError("Shapefile contains no readable features.")
    return features


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
    import os
    import tempfile

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
    import os
    import tempfile

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
