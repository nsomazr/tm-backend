import json
import zipfile
from io import BytesIO

from celery import shared_task
from django.db import transaction

from .models import LayerUpload, LayerVersion, MapFeature, MapLayer
from .shapefile_utils import detect_file_type, parse_upload_content


def import_features_for_layer(layer: MapLayer, features_data: list, source: str = "import") -> int:
    """Replace active features on a layer with parsed GeoJSON features."""
    new_features = []
    for feat in features_data:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {}) or {}
        lat, lng = _extract_point_coords(geom)
        new_features.append(
            MapFeature(
                layer=layer,
                geometry=geom,
                properties=props,
                latitude=lat,
                longitude=lng,
                label=props.get("name", props.get("label", "")),
            )
        )
    MapFeature.objects.bulk_create(new_features)
    return len(new_features)


@shared_task
def process_layer_upload(upload_id):
    upload = LayerUpload.objects.select_related("layer").get(id=upload_id)
    upload.status = LayerUpload.Status.PROCESSING
    upload.save(update_fields=["status"])

    try:
        layer = upload.layer
        content = upload.file.read()
        filename = upload.file.name

        ft = upload.file_type
        if ft == "geojson" and detect_file_type(filename) == "shapefile":
            ft = "shapefile"
        if ft in ("geojson", "json", "shapefile", "zip", ""):
            features_data = parse_upload_content(content, filename, ft or None)
        else:
            features_data = parse_upload_content(content, filename, ft)

        with transaction.atomic():
            layer.features.filter(is_active=True).update(is_active=False)
            count = import_features_for_layer(layer, features_data, source=filename)

            layer.current_version += 1
            layer.save(update_fields=["current_version"])

            LayerVersion.objects.create(
                layer=layer,
                version_number=layer.current_version,
                changelog=f"Import from {filename}",
                uploaded_by=upload.uploaded_by,
                feature_count=count,
            )

        upload.status = LayerUpload.Status.COMPLETED
        upload.save(update_fields=["status"])
    except Exception as exc:
        upload.status = LayerUpload.Status.FAILED
        upload.error_message = str(exc)
        upload.save(update_fields=["status", "error_message"])
        raise


def _extract_geojson_from_zip(content):
    with zipfile.ZipFile(BytesIO(content)) as zf:
        for name in zf.namelist():
            if name.endswith(".geojson") or name.endswith(".json"):
                return json.loads(zf.read(name))
    raise ValueError("No GeoJSON file found in zip archive.")


def _extract_point_coords(geometry):
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates")
    if not coords:
        return None, None
    if gtype == "Point":
        return coords[1], coords[0]
    if gtype == "LineString" and coords:
        lngs = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return sum(lats) / len(lats), sum(lngs) / len(lngs)
    if gtype == "Polygon" and coords:
        ring = coords[0]
        if ring:
            lngs = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            return sum(lats) / len(lats), sum(lngs) / len(lngs)
    if gtype == "MultiPolygon" and coords:
        ring = coords[0][0]
        if ring:
            lngs = [c[0] for c in ring]
            lats = [c[1] for c in ring]
            return sum(lats) / len(lats), sum(lngs) / len(lngs)
    return None, None
