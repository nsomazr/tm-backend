import json
import logging
import zipfile
from io import BytesIO

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)

from .models import LayerUpload, LayerVersion, MapFeature, MapLayer
from .shapefile_utils import detect_file_type, parse_upload_content
from .upload_security import check_disk_headroom, friendly_upload_error

DEFAULT_FEATURE_BULK_BATCH_SIZE = 25
DEFAULT_MAX_BATCH_BYTES = 1_048_576  # 1 MiB
DEFAULT_MAX_GEOMETRY_BYTES = 512 * 1024


def _feature_insert_bytes(feature: MapFeature) -> int:
    geom = json.dumps(feature.geometry, separators=(",", ":"))
    props = json.dumps(feature.properties, separators=(",", ":"))
    return len(geom) + len(props) + len(feature.label or "")


def _bulk_create_chunk(features: list[MapFeature]) -> None:
    if not features:
        return
    try:
        MapFeature.objects.bulk_create(features)
    except OperationalError as exc:
        if "max_allowed_packet" not in str(exc).lower() or len(features) <= 1:
            raise
        mid = len(features) // 2
        _bulk_create_chunk(features[:mid])
        _bulk_create_chunk(features[mid:])


def _bulk_create_features(features: list[MapFeature]) -> None:
    """Insert features in size-limited batches to stay under MySQL max_allowed_packet."""
    if not features:
        return
    max_count = max(1, int(getattr(settings, "MAP_FEATURE_BULK_BATCH_SIZE", DEFAULT_FEATURE_BULK_BATCH_SIZE)))
    max_bytes = int(getattr(settings, "MAP_FEATURE_MAX_BATCH_BYTES", DEFAULT_MAX_BATCH_BYTES))
    batch: list[MapFeature] = []
    batch_bytes = 0
    for feature in features:
        nbytes = _feature_insert_bytes(feature)
        if batch and (len(batch) >= max_count or batch_bytes + nbytes > max_bytes):
            _bulk_create_chunk(batch)
            batch = []
            batch_bytes = 0
        batch.append(feature)
        batch_bytes += nbytes
    if batch:
        _bulk_create_chunk(batch)


def _prepare_geometry(geometry: dict, layer: MapLayer) -> dict:
    if layer.layer_type != MapLayer.LayerType.POLYGON:
        return geometry
    gtype = geometry.get("type", "")
    if gtype not in ("Polygon", "MultiPolygon"):
        return geometry
    max_geom_bytes = int(getattr(settings, "MAP_FEATURE_MAX_GEOMETRY_BYTES", DEFAULT_MAX_GEOMETRY_BYTES))
    if len(json.dumps(geometry, separators=(",", ":"))) <= max_geom_bytes:
        return geometry
    from apps.geography.admin_boundary_service import simplify_geometry

    simplified = simplify_geometry(geometry, tolerance_deg=0.01)
    if len(json.dumps(simplified, separators=(",", ":"))) > max_geom_bytes:
        simplified = simplify_geometry(geometry, tolerance_deg=0.05)
    return simplified


def import_features_for_layer(layer: MapLayer, features_data: list, source: str = "import") -> int:
    """Bulk-create parsed GeoJSON features on a layer. Returns count of new features."""
    new_features = []
    for feat in features_data:
        geom = _prepare_geometry(feat.get("geometry", {}), layer)
        props = feat.get("properties", {}) or {}
        lat, lng = _extract_point_coords(geom)
        new_features.append(
            MapFeature(
                layer=layer,
                geometry=geom,
                properties=props,
                latitude=lat,
                longitude=lng,
                label=str(props.get("name", props.get("label", "")))[:255],
            )
        )
    _bulk_create_features(new_features)
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
        check_disk_headroom(boundary=False)

        ft = upload.file_type
        if ft == "geojson" and detect_file_type(filename) == "shapefile":
            ft = "shapefile"
        if ft in ("geojson", "json", "shapefile", "zip", "csv", ""):
            features_data = parse_upload_content(content, filename, ft or None, boundary=False)
        else:
            features_data = parse_upload_content(content, filename, ft, boundary=False)

        append = upload.import_mode == LayerUpload.ImportMode.APPEND
        with transaction.atomic():
            if not append:
                layer.features.filter(is_active=True).update(is_active=False)
            count = import_features_for_layer(layer, features_data, source=filename)

            layer.current_version += 1
            update_fields = ["current_version"]
            if count > 0:
                layer.is_active = True
                update_fields.append("is_active")
            layer.save(update_fields=update_fields)

            changelog = f"Append from {filename}" if append else f"Import from {filename}"
            LayerVersion.objects.create(
                layer=layer,
                version_number=layer.current_version,
                changelog=changelog,
                uploaded_by=upload.uploaded_by,
                feature_count=count,
            )

        upload.status = LayerUpload.Status.COMPLETED
        # The parsed coordinates now live in the DB; delete the raw uploaded
        # shapefile so we don't retain a second plaintext copy at rest.
        try:
            if upload.file:
                upload.file.delete(save=False)
        except Exception:
            logger.warning("Could not delete raw upload file for upload %s", upload.id)
        upload.save(update_fields=["status", "file"])
    except OperationalError as exc:
        upload.status = LayerUpload.Status.FAILED
        upload.error_message = friendly_upload_error(exc)
        upload.save(update_fields=["status", "error_message"])
        raise
    except Exception as exc:
        upload.status = LayerUpload.Status.FAILED
        upload.error_message = friendly_upload_error(exc)
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
