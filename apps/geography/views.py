from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from apps.accounts.permissions import IsAdminUser

from .models import Country, Region
from .serializers import CountrySerializer, RegionSerializer


class CountryViewSet(viewsets.ModelViewSet):
    queryset = Country.objects.filter(is_active=True)
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "code"

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return super().get_permissions()


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.filter(is_active=True).select_related("country")
    serializer_class = RegionSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filterset_fields = ["country"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return super().get_permissions()
