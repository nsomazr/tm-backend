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
    queryset = Mineral.objects.filter(is_active=True).select_related("category", "country")
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
        if self.action in ("create", "destroy"):
            return [IsAdminUser()]
        if self.action in ("update", "partial_update"):
            from apps.accounts.permissions import IsMineralManagerOrAdmin
            return [IsMineralManagerOrAdmin()]
        return super().get_permissions()

    def perform_update(self, serializer):
        instance = serializer.save()
        sync = self.request.data.get("sync_layer_colors")
        if sync and "color" in serializer.validated_data:
            from apps.maps.models import MapLayer

            for layer in MapLayer.objects.filter(mineral=instance, is_active=True):
                style = dict(layer.style or {})
                style["fill"] = instance.color
                if layer.layer_type in ("polygon", "point"):
                    style["stroke"] = instance.color if layer.layer_type == "polygon" else "#ffffff"
                layer.style = style
                layer.save(update_fields=["style"])

    @action(detail=True, methods=["get"])
    def layers(self, request, slug=None):
        mineral = self.get_object()
        from apps.maps.access import filter_layers_for_user
        from apps.maps.models import MapLayer

        layers = MapLayer.objects.filter(mineral=mineral, is_active=True).select_related(
            "mineral", "region"
        )
        layers = filter_layers_for_user(layers, request.user)
        serializer = MapLayerSerializer(layers, many=True, context={"request": request})
        return Response(serializer.data)


class MineralManagerAssignmentViewSet(viewsets.ModelViewSet):
    queryset = MineralManagerAssignment.objects.select_related("user", "mineral", "assigned_by")
    serializer_class = MineralManagerAssignmentSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["user", "mineral"]
