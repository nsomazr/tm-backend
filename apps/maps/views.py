import json

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminUser, IsMineralManagerOrAdmin
from apps.compliance.views import log_audit
from apps.minerals.permissions import get_managed_mineral_ids, user_can_manage_mineral

from .access import filter_layers_for_user, layers_with_mapped_data, user_has_map_detail_access
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

    def _manager_roles(self):
        return (User.Role.SUPER_ADMIN, User.Role.ADMIN, User.Role.MINERAL_MANAGER)

    def _can_manage_layers(self):
        user = self.request.user
        return user.is_authenticated and user.role in self._manager_roles()

    def _include_inactive_list(self):
        return (
            self.action == "list"
            and self._can_manage_layers()
            and self.request.query_params.get("include_inactive") == "1"
        )

    def get_queryset(self):
        if self.action in ("list", "retrieve", "geojson"):
            if self._include_inactive_list():
                qs = MapLayer.objects.all().select_related("mineral", "region")
            else:
                qs = MapLayer.objects.filter(is_active=True).select_related("mineral", "region")
        else:
            qs = MapLayer.objects.all().select_related("mineral", "region")

        mineral_slug = self.request.query_params.get("mineral_slug")
        if mineral_slug:
            qs = qs.filter(mineral__slug=mineral_slug)

        if self.action in ("list", "retrieve", "geojson"):
            if self._include_inactive_list():
                managed = get_managed_mineral_ids(self.request.user)
                qs = qs.select_related("created_by", "mineral", "region").prefetch_related(
                    Prefetch(
                        "versions",
                        queryset=LayerVersion.objects.select_related("uploaded_by").order_by(
                            "-version_number"
                        ),
                    )
                )
                if managed is not None:
                    return qs.filter(mineral_id__in=managed).order_by("z_index", "name")
                return qs.order_by("z_index", "name")
            qs = layers_with_mapped_data(qs)
            return filter_layers_for_user(qs, self.request.user).order_by("z_index", "name")

        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(mineral_id__in=managed).order_by("z_index", "name")
        return qs.order_by("z_index", "name")

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAdminUser()]
        if self.action in ("create", "update", "partial_update", "bulk_import", "reorder", "export", "sample_shapefile"):
            return [IsMineralManagerOrAdmin()]
        return super().get_permissions()

    def get_throttles(self):
        # Map tiles are fetched in bursts on load; skip default anon/user throttling.
        if self.action in ("list", "retrieve", "geojson"):
            return []
        return super().get_throttles()

    def perform_create(self, serializer):
        from django.utils.text import slugify

        from .layer_defaults import get_or_create_general_mineral

        name = serializer.validated_data.get("name", "layer")
        slug = slugify(name)
        counter = 1
        mineral = serializer.validated_data.get("mineral") or get_or_create_general_mineral()
        base = slug
        while MapLayer.objects.filter(mineral=mineral, slug=slug).exists():
            slug = f"{base}-{counter}"
            counter += 1
        layer = serializer.save(created_by=self.request.user, slug=slug, mineral=mineral)
        log_audit(
            self.request,
            "layer_create",
            "MapLayer",
            layer.id,
            {
                "slug": layer.slug,
                "name": layer.name,
                "mineral": layer.mineral.name,
                "layer_type": layer.layer_type,
            },
        )

    def perform_update(self, serializer):
        layer = serializer.save()
        log_audit(
            self.request,
            "layer_update",
            "MapLayer",
            layer.id,
            {
                "slug": layer.slug,
                "name": layer.name,
                "changes": {
                    key: serializer.validated_data[key]
                    for key in serializer.validated_data
                },
            },
        )

    def perform_destroy(self, instance):
        log_audit(
            self.request,
            "layer_delete",
            "MapLayer",
            instance.id,
            {"slug": instance.slug, "name": instance.name, "mineral": instance.mineral.name},
        )
        instance.delete()

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

        max_bytes = getattr(settings, "MAP_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)
        if upload_file.size > max_bytes:
            return Response(
                {"detail": f"File too large. Maximum size is {max_bytes // (1024 * 1024)} MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_type = request.data.get("file_type") or detect_file_type(upload_file.name)
        upload = LayerUpload.objects.create(
            layer=layer,
            file=upload_file,
            file_type=file_type,
            uploaded_by=request.user,
        )
        from apps.maps.tasks import process_layer_upload

        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or settings.DEBUG:
            process_layer_upload(upload.id)
        else:
            process_layer_upload.delay(upload.id)
        upload.refresh_from_db()
        log_audit(
            request,
            "layer_upload",
            "MapLayer",
            layer.id,
            {
                "upload_id": upload.id,
                "filename": upload_file.name,
                "layer_slug": layer.slug,
                "layer_name": layer.name,
                "mineral": layer.mineral.name,
                "file_type": file_type,
            },
        )
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
        layers = list(MapLayer.objects.filter(id__in=layer_ids))
        if len(layers) != len(layer_ids):
            return Response({"detail": "One or more layers were not found."}, status=status.HTTP_400_BAD_REQUEST)
        for layer in layers:
            if not user_can_manage_mineral(request.user, layer.mineral_id):
                return Response({"detail": "Not allowed to reorder one or more layers."}, status=status.HTTP_403_FORBIDDEN)
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
    queryset = LayerVersion.objects.select_related("layer", "layer__mineral", "uploaded_by")
    serializer_class = LayerVersionSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    filterset_fields = ["layer"]

    def get_queryset(self):
        qs = super().get_queryset()
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(layer__mineral_id__in=managed)
        return qs


class LayerUploadViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LayerUpload.objects.select_related(
        "layer", "layer__mineral", "uploaded_by"
    ).order_by("-created_at")
    serializer_class = LayerUploadSerializer
    permission_classes = [IsMineralManagerOrAdmin]
    filterset_fields = ["layer", "status", "uploaded_by"]

    def get_queryset(self):
        qs = super().get_queryset()
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(layer__mineral_id__in=managed)
        manager_only = self.request.query_params.get("manager_only")
        if manager_only == "1" and self.request.user.is_admin_user:
            return qs.filter(uploaded_by__role=User.Role.MINERAL_MANAGER)
        return qs
