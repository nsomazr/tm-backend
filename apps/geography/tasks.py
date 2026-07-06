from celery import shared_task

from apps.maps.shapefile_utils import parse_upload_content

from .admin_boundary_service import import_uploaded_boundaries
from .boundary_import_job import _features_from_parsed


@shared_task(bind=True)
def process_boundary_upload(self, country_code: str, level: int, content: bytes, filename: str, replace: bool = True):
    features_data = parse_upload_content(content, filename, boundary=True)
    features = _features_from_parsed(features_data)

    def progress(done: int, total: int) -> None:
        if done % 50 != 0 and done != total:
            return
        self.update_state(
            state="PROGRESS",
            meta={
                "status": "processing",
                "phase": "importing",
                "done": done,
                "total": total,
            },
        )

    count = import_uploaded_boundaries(
        country_code,
        level,
        features,
        replace=replace,
        progress_cb=progress,
    )
    return {"imported": count, "country": country_code, "level": level}
