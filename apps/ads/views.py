from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser
from apps.compliance.views import log_audit

from .models import Ad, AdEvent
from .serializers import AdAdminSerializer, AdPublicSerializer, AdTrackSerializer
from .services import ads_for_placement, build_ad_admin_stats, record_ad_event


class AdServeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        placement = request.query_params.get("placement", "")
        country = request.query_params.get("country", "TZ")
        ads = ads_for_placement(
            placement,
            user=request.user,
            country_code=country,
        )
        serializer = AdPublicSerializer(ads, many=True, context={"request": request})
        return Response(serializer.data)


class AdTrackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AdTrackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            ad = Ad.objects.get(pk=data["ad_id"])
        except Ad.DoesNotExist:
            return Response({"detail": "Ad not found."}, status=status.HTTP_404_NOT_FOUND)
        if not ad.is_live():
            return Response({"detail": "Ad is not active."}, status=status.HTTP_400_BAD_REQUEST)
        if data["placement"] not in (ad.placements or []):
            return Response({"detail": "Invalid placement for this ad."}, status=status.HTTP_400_BAD_REQUEST)

        session_key = request.headers.get("X-Ad-Session", "") or request.session.session_key or ""
        kind = AdEvent.Kind.IMPRESSION if data["kind"] == "impression" else AdEvent.Kind.CLICK
        record_ad_event(
            ad,
            kind=kind,
            placement=data["placement"],
            user=request.user,
            session_key=session_key,
        )
        return Response({"ok": True})


class AdAdminStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(build_ad_admin_stats())


class AdAdminListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = AdAdminSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Ad.objects.all().select_related("created_by")
    pagination_class = None

    def perform_create(self, serializer):
        ad = serializer.save()
        log_audit(
            self.request,
            "ad_create",
            "Ad",
            ad.id,
            {"title": ad.title, "company": ad.company_name, "placements": ad.placements},
        )


class AdAdminDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = AdAdminSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Ad.objects.all().select_related("created_by")
    lookup_field = "pk"

    def perform_update(self, serializer):
        ad = serializer.save()
        log_audit(
            self.request,
            "ad_update",
            "Ad",
            ad.id,
            {"title": ad.title, "is_active": ad.is_active, "is_hidden": ad.is_hidden},
        )

    def perform_destroy(self, instance):
        log_audit(
            self.request,
            "ad_delete",
            "Ad",
            instance.id,
            {"title": instance.title, "company": instance.company_name},
        )
        instance.delete()
