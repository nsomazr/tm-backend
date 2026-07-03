import json

from django.db import transaction
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminUser, IsMineralManagerOrAdmin
from apps.minerals.permissions import get_managed_mineral_ids, user_can_manage_mineral

from .access import filter_layers_for_user, user_has_map_detail_access
from .filters import MapLayerFilter
from .models import LayerUpload, LayerVersion, MapFeature, MapLayer
from .shapefile_utils import detect_file_type
from .serializers import (
    LayerReorderSerializer,
    LayerUploadSerializer,
    LayerVersionSerializer,
    MapFeatureSerializer,
    MapLayerDetailSerializer,
    MapLayerSerializer,
)


class MapLayerViewSet(viewsets.ModelViewSet):
    queryset = MapLayer.objects.filter(is_active=True).select_related("mineral", "region")
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_class = MapLayerFilter
    search_fields = ["name", "name_sw"]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MapLayerDetailSerializer
        return MapLayerSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        mineral_slug = self.request.query_params.get("mineral_slug")
        if mineral_slug:
            qs = qs.filter(mineral__slug=mineral_slug)
        if self.action in ("list", "retrieve", "geojson"):
            return filter_layers_for_user(qs, self.request.user)
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(mineral_id__in=managed)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "bulk_import", "reorder", "export", "sample_shapefile"):
            return [IsMineralManagerOrAdmin()]
        return super().get_permissions()

    def perform_create(self, serializer):
        from django.utils.text import slugify
        name = serializer.validated_data.get("name", "layer")
        slug = slugify(name)
        counter = 1
        mineral = serializer.validated_data["mineral"]
        base = slug
        while MapLayer.objects.filter(mineral=mineral, slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        serializer.save(created_by=self.request.user, slug=slug)

    @action(detail=True, methods=["get"])
    def geojson(self, request, slug=None):
        layer = self.get_object()
        features = layer.features.filter(is_active=True)
        has_detail = user_has_map_detail_access(request.user)

        def props_for(f):
            base = {
                "id": f.id,
                "layer": layer.slug,
                "mineral": layer.mineral.slug,
            }
            if has_detail:
                return {**f.properties, **base, "label": f.label}
            return {**base, "label": f.label or ""}

        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": f.geometry,
                    "properties": props_for(f),
                }
                for f in features
            ],
        }
        return Response(fc)

    @action(detail=True, methods=["get"])
    def export(self, request, slug=None):
        layer = self.get_object()
        features = layer.features.filter(is_active=True)
        fc = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": f.geometry, "properties": f.properties}
                for f in features
            ],
        }
        response = HttpResponse(
            json.dumps(fc, indent=2),
            content_type="application/geo+json",
        )
        response["Content-Disposition"] = f'attachment; filename="{layer.slug}.geojson"'
        return response

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def bulk_import(self, request, slug=None):
        layer = self.get_object()
        if not user_can_manage_mineral(request.user, layer.mineral_id):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        upload_file = request.FILES.get("file")
        if not upload_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        file_type = request.data.get("file_type") or detect_file_type(upload_file.name)
        upload = LayerUpload.objects.create(
            layer=layer,
            file=upload_file,
            file_type=file_type,
            uploaded_by=request.user,
        )
        from apps.maps.tasks import process_layer_upload
        from django.conf import settings

        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or settings.DEBUG:
            process_layer_upload(upload.id)
        else:
            process_layer_upload.delay(upload.id)
        upload.refresh_from_db()
        return Response(LayerUploadSerializer(upload).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def sample_shapefile(self, request, slug=None):
        """Download sample shapefile ZIP for this layer (admin/manager)."""
        import os
        from django.conf import settings
        from django.http import FileResponse

        layer = self.get_object()
        path = os.path.join(settings.BASE_DIR, "sample_data", "shapefiles", f"{layer.slug}.zip")
        if not os.path.exists(path):
            return Response({"detail": "Sample shapefile not generated yet. Run generate_sample_shapefiles."}, status=404)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=f"{layer.slug}-sample.zip")

    @action(detail=False, methods=["patch"])
    def reorder(self, request):
        serializer = LayerReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        layer_ids = serializer.validated_data["layer_ids"]
        with transaction.atomic():
            for index, layer_id in enumerate(layer_ids):
                MapLayer.objects.filter(id=layer_id).update(z_index=index)
        return Response({"detail": "Layers reordered."})


class MapFeatureViewSet(viewsets.ModelViewSet):
    queryset = MapFeature.objects.filter(is_active=True).select_related("layer")
    serializer_class = MapFeatureSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    filterset_fields = ["layer"]

    def get_queryset(self):
        qs = super().get_queryset()
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(layer__mineral_id__in=managed)
        return qs

    def perform_create(self, serializer):
        layer = serializer.validated_data["layer"]
        if not user_can_manage_mineral(self.request.user, layer.mineral_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot manage features for this mineral.")
        serializer.save()


class LayerVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LayerVersion.objects.select_related("layer", "uploaded_by")
    serializer_class = LayerVersionSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    filterset_fields = ["layer"]

    def get_queryset(self):
        qs = super().get_queryset()
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(layer__mineral_id__in=managed)
        return qs
