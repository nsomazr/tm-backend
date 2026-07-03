from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import AuditLog, LicenseAgreement, TermsAcceptance, TermsVersion
from .serializers import (
    AuditLogSerializer,
    LicenseAgreementSerializer,
    TermsAcceptanceSerializer,
    TermsVersionSerializer,
)


def log_audit(request, action, resource_type, resource_id="", details=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=details or {},
        ip_address=_get_client_ip(request),
    )


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class ActiveTermsView(generics.RetrieveAPIView):
    serializer_class = TermsVersionSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return TermsVersion.objects.filter(is_active=True).first()


class AcceptTermsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        terms = TermsVersion.objects.filter(is_active=True).first()
        if not terms:
            return Response({"detail": "No active terms."}, status=status.HTTP_404_NOT_FOUND)
        acceptance, created = TermsAcceptance.objects.get_or_create(
            user=request.user,
            terms=terms,
            defaults={"ip_address": _get_client_ip(request)},
        )
        log_audit(request, "accept_terms", "TermsVersion", terms.id)
        return Response(TermsAcceptanceSerializer(acceptance).data)


class LicenseAgreementListView(generics.ListCreateAPIView):
    queryset = LicenseAgreement.objects.all().prefetch_related("minerals", "regions")
    serializer_class = LicenseAgreementSerializer
    permission_classes = [IsAdminUser]


class LicenseAgreementDetailView(generics.RetrieveUpdateAPIView):
    queryset = LicenseAgreement.objects.all()
    serializer_class = LicenseAgreementSerializer
    permission_classes = [IsAdminUser]

    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.status == LicenseAgreement.Status.APPROVED:
            instance.approved_by = self.request.user
            instance.save(update_fields=["approved_by"])
        log_audit(self.request, "update_license", "LicenseAgreement", instance.id)


class AuditLogListView(generics.ListAPIView):
    queryset = AuditLog.objects.select_related("actor").order_by("-created_at")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["action", "resource_type"]
