from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminUser, IsSuperAdmin
from apps.maps.serializers import MapLayerSerializer

from .models import Mineral, MineralCategory, MineralManagerAssignment
from .permissions import get_managed_mineral_ids
from .serializers import (
    MineralCategorySerializer,
    MineralManagerAssignmentSerializer,
    MineralSerializer,
    SyncMineralManagerAssignmentsSerializer,
)


class MineralCategoryViewSet(viewsets.ModelViewSet):
    queryset = MineralCategory.objects.all()
    serializer_class = MineralCategorySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "slug"

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return super().get_permissions()


class MineralViewSet(viewsets.ModelViewSet):
    queryset = Mineral.objects.filter(is_active=True).select_related(
        "category", "country"
    ).prefetch_related("associated_layers")
    serializer_class = MineralSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "slug"
    filterset_fields = ["country", "category"]
    search_fields = ["name", "name_sw"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve"):
            return qs
        managed = get_managed_mineral_ids(self.request.user)
        if managed is not None:
            return qs.filter(id__in=managed)
        return qs

    def get_permissions(self):
        if self.action in ("create", "destroy", "update", "partial_update"):
            return [IsAdminUser()]
        return super().get_permissions()

    def perform_update(self, serializer):
        instance = serializer.save()
        sync = self.request.data.get("sync_layer_colors")
        if sync and "color" in serializer.validated_data:
            from apps.maps.models import MapLayer
            from apps.minerals.color_utils import enrich_layer_style

            for layer in MapLayer.objects.filter(mineral=instance, is_active=True):
                style = enrich_layer_style(layer.style or {}, layer.layer_type)
                hex_color = instance.color
                style["fill"] = hex_color
                if layer.layer_type in ("polygon", "point"):
                    style["stroke"] = hex_color if layer.layer_type == "polygon" else "#ffffff"
                elif layer.layer_type == "line":
                    style["stroke"] = hex_color
                style = enrich_layer_style(style, layer.layer_type)
                layer.style = style
                layer.save(update_fields=["style"])

    @action(detail=True, methods=["get"])
    def layers(self, request, slug=None):
        mineral = self.get_object()
        from apps.maps.access import filter_layers_for_user, layers_with_mapped_data
        from apps.maps.models import MapLayer

        owned = MapLayer.objects.filter(mineral=mineral, is_active=True)
        associated = mineral.associated_layers.filter(is_active=True)
        layers = (owned | associated).distinct().select_related("mineral", "region")
        layers = layers_with_mapped_data(layers)
        layers = filter_layers_for_user(layers, request.user)
        serializer = MapLayerSerializer(layers, many=True, context={"request": request})
        return Response(serializer.data)


class MineralManagerAssignmentViewSet(viewsets.ModelViewSet):
    queryset = MineralManagerAssignment.objects.select_related("user", "mineral", "assigned_by")
    serializer_class = MineralManagerAssignmentSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["user", "mineral"]

    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Set all mineral/commodity assignments for one manager."""
        serializer = SyncMineralManagerAssignmentsSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        assignments = serializer.save()
        output = MineralManagerAssignmentSerializer(
            assignments,
            many=True,
            context={"request": request},
        )
        return Response(output.data)
