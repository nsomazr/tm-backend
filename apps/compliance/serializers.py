from rest_framework import serializers

from .models import AuditLog, LicenseAgreement, TermsAcceptance, TermsVersion


class TermsVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TermsVersion
        fields = ("id", "version", "title", "content", "is_active", "published_at")


class TermsAcceptanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TermsAcceptance
        fields = ("id", "terms", "accepted_at")


class LicenseAgreementSerializer(serializers.ModelSerializer):
    class Meta:
        model = LicenseAgreement
        fields = (
            "id",
            "company_name",
            "contact_name",
            "contact_email",
            "minerals",
            "regions",
            "terms",
            "price",
            "currency",
            "status",
            "start_date",
            "end_date",
            "created_at",
        )
        read_only_fields = ("status", "created_at")


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id",
            "actor",
            "actor_name",
            "action",
            "resource_type",
            "resource_id",
            "details",
            "ip_address",
            "created_at",
        )
