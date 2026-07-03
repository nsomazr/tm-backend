from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import LayerVersionViewSet, MapFeatureViewSet, MapLayerViewSet

router = DefaultRouter()
router.register("layers", MapLayerViewSet, basename="map-layer")
router.register("features", MapFeatureViewSet, basename="map-feature")
router.register("versions", LayerVersionViewSet, basename="layer-version")

urlpatterns = [
    path("", include(router.urls)),
]
