from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CountryViewSet, RegionViewSet

router = DefaultRouter()
router.register("countries", CountryViewSet, basename="country")
router.register("regions", RegionViewSet, basename="region")

urlpatterns = [
    path("", include(router.urls)),
]
