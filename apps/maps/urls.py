from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    LayerUploadViewSet,
    LayerVersionViewSet,
    MapFeatureViewSet,
    MapLayerViewSet,
    SavedExplorationViewSet,
    map_platform_settings,
)

router = DefaultRouter()
router.register("layers", MapLayerViewSet, basename="map-layer")
router.register("features", MapFeatureViewSet, basename="map-feature")
router.register("versions", LayerVersionViewSet, basename="layer-version")
router.register("uploads", LayerUploadViewSet, basename="layer-upload")
router.register("saved-explorations", SavedExplorationViewSet, basename="saved-exploration")

urlpatterns = [
    path("settings/", map_platform_settings, name="map-platform-settings"),
    path("", include(router.urls)),
]
