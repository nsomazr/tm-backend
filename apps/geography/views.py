from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import models

from apps.accounts.permissions import IsAdminUser
from apps.accounts.throttling import AdminUploadThrottle
from apps.maps.upload_security import (
    UploadValidationError,
    check_disk_headroom,
    friendly_upload_error,
    validate_upload_filename,
    validate_upload_size,
)

from .admin_boundary_service import (
    boundaries_feature_collection,
    import_uploaded_boundaries,
    lookup_boundaries_at_point,
)
from .boundary_import_job import get_import_status, start_boundary_import
from .boundary_map_cache import build_village_display_cache, load_village_display_cache
from .country_geo import country_focus_payload, ensure_country
from .models import AdminBoundary, BoundaryGeologyDocument, Country, Region
from .serializers import (
    AdminBoundaryGeologySerializer,
    AdminBoundaryGeologyUpdateSerializer,
    AdminBoundaryListItemSerializer,
    BoundaryGeologyDocumentSerializer,
    CountrySerializer,
    RegionSerializer,
)


class CountryViewSet(viewsets.ModelViewSet):
    queryset = Country.objects.filter(is_active=True).order_by("name")
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "code"
    pagination_class = None

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="with-boundaries")
    def with_boundaries(self, request):
        """Countries that have at least one admin-uploaded boundary shapefile."""
        qs = (
            Country.objects.filter(
                is_active=True,
                admin_boundaries__source=AdminBoundary.Source.ADMIN_UPLOAD,
            )
            .distinct()
            .order_by("name")
        )
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def focus(self, request, code=None):
        country = self.get_object()
        return Response(country_focus_payload(country))

    @action(detail=True, methods=["get"], url_path="boundaries")
    def boundaries(self, request, code=None):
        country = self.get_object()
        raw = request.query_params.get("levels", "0,1,2,3,4")
        levels = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
        if not levels:
            levels = [0, 1, 2]
        display = str(request.query_params.get("display", "false")).lower() in ("1", "true", "yes")
        offset = max(0, int(request.query_params.get("offset", 0) or 0))
        limit_raw = request.query_params.get("limit")
        limit: int | None = None
        if limit_raw not in (None, ""):
            limit = max(1, min(5000, int(limit_raw)))

        if levels == [4] and display:
            cached = load_village_display_cache(country.code, offset=offset, limit=limit)
            if cached is not None:
                return Response(cached)

        return Response(
            boundaries_feature_collection(
                country,
                levels,
                display=display,
                offset=offset,
                limit=limit,
            )
        )

    @action(detail=True, methods=["get"], url_path="boundaries/at")
    def boundaries_at(self, request, code=None):
        country = self.get_object()
        try:
            lat = float(request.query_params.get("lat", ""))
            lng = float(request.query_params.get("lng", ""))
        except (TypeError, ValueError):
            return Response({"detail": "lat and lng are required."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(lookup_boundaries_at_point(country, lat, lng))


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.filter(is_active=True).select_related("country")
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_fields = ["country"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return super().get_permissions()


class AdminBoundaryImportView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AdminUploadThrottle]

    def post(self, request):
        country_code = (request.data.get("country") or "TZ").upper()
        try:
            level = int(request.data.get("level", 1))
        except (TypeError, ValueError):
            return Response({"detail": "level must be 0, 1, 2, 3, or 4."}, status=status.HTTP_400_BAD_REQUEST)
        if level not in (0, 1, 2, 3, 4):
            return Response({"detail": "level must be 0, 1, 2, 3, or 4."}, status=status.HTTP_400_BAD_REQUEST)

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_upload_filename(upload.name)
            validate_upload_size(upload.size, boundary=True)
            check_disk_headroom(boundary=True)
        except UploadValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        replace = str(request.data.get("replace", "true")).lower() in ("1", "true", "yes")
        async_mode = str(request.data.get("async", "false")).lower() in ("1", "true", "yes")

        if not ensure_country(country_code):
            return Response({"detail": f"Country {country_code} not found."}, status=status.HTTP_404_NOT_FOUND)

        content = upload.read()
        filename = upload.name

        if async_mode:
            task_id = start_boundary_import(
                country_code,
                level,
                content,
                filename,
                replace=replace,
            )
            return Response({"task_id": task_id, "status": "processing"}, status=status.HTTP_202_ACCEPTED)

        from apps.maps.shapefile_utils import parse_upload_content

        try:
            features_data = parse_upload_content(content, filename, boundary=True)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        features = [
            {"type": "Feature", "properties": f.get("properties", {}), "geometry": f.get("geometry")}
            for f in features_data
            if f.get("geometry")
        ]
        if not features:
            return Response({"detail": "No features found in upload."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            check_disk_headroom(boundary=True)
            count = import_uploaded_boundaries(country_code, level, features, replace=replace)
        except Exception as exc:
            return Response(
                {"detail": friendly_upload_error(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"imported": count, "country": country_code, "level": level})


class AdminBoundaryImportStatusView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, task_id: str):
        payload = get_import_status(task_id)
        if not payload:
            return Response({"detail": "Import task not found or expired."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"task_id": task_id, **payload})


class AdminBoundaryListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        country_code = request.query_params.get("country", "TZ").upper()
        qs = AdminBoundary.objects.filter(
            country__code=country_code,
            source=AdminBoundary.Source.ADMIN_UPLOAD,
        ).order_by("level", "name")
        return Response(
            {
                "country": country_code,
                "counts": {
                    "0": qs.filter(level=0).count(),
                    "1": qs.filter(level=1).count(),
                    "2": qs.filter(level=2).count(),
                    "3": qs.filter(level=3).count(),
                    "4": qs.filter(level=4).count(),
                },
                "last_updated": qs.order_by("-updated_at").values_list("updated_at", flat=True).first(),
            }
        )


class AdminBoundaryItemsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        country_code = request.query_params.get("country", "TZ").upper()
        level_raw = request.query_params.get("level")
        query = (request.query_params.get("q") or "").strip()
        qs = (
            AdminBoundary.objects.filter(
                country__code=country_code,
                source=AdminBoundary.Source.ADMIN_UPLOAD,
            )
            .annotate(geology_document_count=models.Count("geology_documents"))
            .order_by("level", "name")
        )
        if level_raw not in (None, ""):
            try:
                qs = qs.filter(level=int(level_raw))
            except (TypeError, ValueError):
                return Response({"detail": "level must be 0–4."}, status=status.HTTP_400_BAD_REQUEST)
        if query:
            qs = qs.filter(name__icontains=query)
        qs = qs[:500]
        serializer = AdminBoundaryListItemSerializer(qs, many=True)
        return Response({"country": country_code, "results": serializer.data})


class AdminBoundaryGeologyDetailView(APIView):
    permission_classes = [IsAdminUser]

    def get_object(self, boundary_id: int) -> AdminBoundary:
        return AdminBoundary.objects.prefetch_related("geology_documents").get(
            id=boundary_id,
            source=AdminBoundary.Source.ADMIN_UPLOAD,
        )

    def get(self, request, boundary_id: int):
        try:
            boundary = self.get_object(boundary_id)
        except AdminBoundary.DoesNotExist:
            return Response({"detail": "Boundary not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AdminBoundaryGeologySerializer(boundary).data)

    def patch(self, request, boundary_id: int):
        try:
            boundary = self.get_object(boundary_id)
        except AdminBoundary.DoesNotExist:
            return Response({"detail": "Boundary not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminBoundaryGeologyUpdateSerializer(boundary, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        boundary.refresh_from_db()
        return Response(AdminBoundaryGeologySerializer(boundary).data)


class AdminBoundaryGeologyDocumentView(APIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AdminUploadThrottle]

    def post(self, request, boundary_id: int):
        try:
            boundary = AdminBoundary.objects.get(
                id=boundary_id,
                source=AdminBoundary.Source.ADMIN_UPLOAD,
            )
        except AdminBoundary.DoesNotExist:
            return Response({"detail": "Boundary not found."}, status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_upload_filename(upload.name)
            validate_upload_size(upload.size, boundary=False)
            check_disk_headroom(boundary=False)
        except UploadValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        title = (request.data.get("title") or upload.name or "Geological reference").strip()[:200]
        scope = (request.data.get("scope") or "local").strip().lower()
        if scope not in ("local", "regional", "global"):
            scope = "local"

        from apps.reports.context_extraction import extract_text_from_upload

        extracted = extract_text_from_upload(upload)
        doc = BoundaryGeologyDocument.objects.create(
            boundary=boundary,
            title=title,
            scope=scope,
            file=upload,
            extracted_text=extracted,
            uploaded_by=request.user if request.user.is_authenticated else None,
        )
        return Response(BoundaryGeologyDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    def delete(self, request, boundary_id: int, document_id: int):
        deleted, _ = BoundaryGeologyDocument.objects.filter(
            id=document_id,
            boundary_id=boundary_id,
            boundary__source=AdminBoundary.Source.ADMIN_UPLOAD,
        ).delete()
        if not deleted:
            return Response({"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
