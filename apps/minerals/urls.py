from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MineralCategoryViewSet,
    MineralManagerAssignmentViewSet,
    MineralViewSet,
)

router = DefaultRouter()
router.register("categories", MineralCategoryViewSet, basename="mineral-category")
router.register("managers", MineralManagerAssignmentViewSet, basename="mineral-manager")
router.register("", MineralViewSet, basename="mineral")

urlpatterns = [
    path("", include(router.urls)),
]
