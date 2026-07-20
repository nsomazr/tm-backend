from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .conversation_service import send_listing_message
from .geometry_upload import geometry_from_upload
from .models import ListingDocument, ListingInquiry, MarketplaceListing
from .serializers import (
    ListingDocumentSerializer,
    ListingInquiryCreateSerializer,
    ListingInquirySerializer,
    OwnerListingSerializer,
    PublicListingDetailSerializer,
    PublicListingListSerializer,
)


def _require_profile_complete(user) -> None:
    if not getattr(user, "profile_complete", False):
        raise PermissionDenied("Complete your profile before managing marketplace listings.")


def _public_queryset():
    return (
        MarketplaceListing.objects.filter(
            deleted_at__isnull=True,
            status=MarketplaceListing.Status.PUBLISHED,
            show_on_map=True,
        )
        .exclude(geometry={})
        .select_related("country", "owner")
        .prefetch_related("documents")
    )


def _owner_queryset(user):
    return (
        MarketplaceListing.objects.filter(owner=user, deleted_at__isnull=True)
        .annotate(
            inquiry_unread_count=Count("inquiries", filter=Q(inquiries__is_read=False), distinct=True),
            inquiry_count=Count("inquiries", distinct=True),
        )
        .prefetch_related("documents")
        .select_related("country")
    )


def _bbox_filter(qs, params):
    try:
        west = float(params["west"])
        south = float(params["south"])
        east = float(params["east"])
        north = float(params["north"])
    except (KeyError, TypeError, ValueError):
        return qs
    return qs.filter(
        center_lng__gte=west,
        center_lng__lte=east,
        center_lat__gte=south,
        center_lat__lte=north,
    )


class PublicListingListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = PublicListingListSerializer
    pagination_class = None

    def get_queryset(self):
        qs = _public_queryset()
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(summary__icontains=q)
                | Q(description__icontains=q)
                | Q(commodity_labels__icontains=q)
            )
        commodity = (self.request.query_params.get("commodity") or "").strip()
        if commodity:
            qs = qs.filter(commodity_labels__icontains=commodity)
        return _bbox_filter(qs, self.request.query_params)


class PublicListingDetailView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = PublicListingDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return _public_queryset()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        from .analytics import record_listing_event
        from .models import ListingEvent

        record_listing_event(
            instance,
            ListingEvent.Kind.VIEW,
            user=request.user,
            session_key=getattr(request.session, "session_key", "") or "",
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class PublicListingEventCreateView(APIView):
    """Track map clicks, downloads, and Terra summary usage on public listings."""

    permission_classes = [AllowAny]

    def post(self, request, slug):
        listing = _public_queryset().filter(slug=slug).first()
        if not listing:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        kind = (request.data.get("kind") or "").strip()
        from .models import ListingEvent

        allowed = {
            ListingEvent.Kind.MAP_CLICK,
            ListingEvent.Kind.DOCUMENT_DOWNLOAD,
            ListingEvent.Kind.TERRA_SUMMARY,
        }
        if kind not in allowed:
            return Response(
                {"detail": "kind must be map_click, document_download, or terra_summary."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .analytics import record_listing_event

        record_listing_event(
            listing,
            kind,
            user=request.user,
            session_key=getattr(request.session, "session_key", "") or "",
        )
        return Response({"ok": True})


class MyMarketplaceAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .analytics import owner_analytics_payload

        return Response(owner_analytics_payload(request.user))


class PublicListingGeoJsonView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = _public_queryset()
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(summary__icontains=q)
                | Q(commodity_labels__icontains=q)
            )
        commodity = (request.query_params.get("commodity") or "").strip()
        if commodity:
            qs = qs.filter(commodity_labels__icontains=commodity)
        qs = _bbox_filter(qs, request.query_params)

        features = []
        for listing in qs:
            geom = listing.geometry or {}
            if not geom:
                continue
            primary = (listing.primary_mineral or "").strip()
            labels = list(listing.commodity_labels or [])
            if not primary and labels:
                primary = str(labels[0])
            others = list(listing.other_minerals or [])
            if not others and len(labels) > 1:
                others = [str(item) for item in labels[1:]]
            color = "#0f766e"
            try:
                from apps.minerals.geological_colors import match_geological_color

                matched = match_geological_color(primary) if primary else None
                if matched:
                    color = matched
            except Exception:
                pass
            features.append(
                {
                    "type": "Feature",
                    "id": listing.id,
                    "geometry": geom,
                    "properties": {
                        "id": listing.id,
                        "slug": listing.slug,
                        "title": listing.title,
                        "summary": listing.summary,
                        "geometry_type": geom.get("type"),
                        "buffer_km": listing.buffer_km,
                        "commodity_labels": labels,
                        "primary_mineral": primary,
                        "other_minerals": others,
                        "color": color,
                    },
                }
            )
        return Response({"type": "FeatureCollection", "features": features})


class MyListingListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OwnerListingSerializer
    pagination_class = None

    def get_queryset(self):
        return _owner_queryset(self.request.user)

    def perform_create(self, serializer):
        _require_profile_complete(self.request.user)
        country = serializer.validated_data.get("country")
        if country is None:
            from apps.geography.models import Country

            country = Country.objects.filter(code="TZ").first()
        serializer.save(owner=self.request.user, country=country)


class MyListingDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OwnerListingSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return _owner_queryset(self.request.user)

    def perform_update(self, serializer):
        _require_profile_complete(self.request.user)
        serializer.save()

    def perform_destroy(self, instance):
        _require_profile_complete(self.request.user)
        instance.deleted_at = timezone.now()
        instance.status = MarketplaceListing.Status.HIDDEN
        instance.show_on_map = False
        instance.save(update_fields=["deleted_at", "status", "show_on_map", "updated_at"])


class ListingDocumentCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ListingDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_listing(self) -> MarketplaceListing:
        listing = (
            MarketplaceListing.objects.filter(
                pk=self.kwargs["pk"],
                owner=self.request.user,
                deleted_at__isnull=True,
            ).first()
        )
        if not listing:
            raise PermissionDenied("Listing not found.")
        return listing

    def perform_create(self, serializer):
        _require_profile_complete(self.request.user)
        listing = self.get_listing()
        serializer.save(listing=listing, uploaded_by=self.request.user)


class ListingDocumentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, doc_id):
        _require_profile_complete(request.user)
        doc = ListingDocument.objects.filter(
            pk=doc_id,
            listing_id=pk,
            listing__owner=request.user,
            listing__deleted_at__isnull=True,
        ).first()
        if not doc:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListingInquiryCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        listing = _public_queryset().filter(slug=slug).first()
        if not listing:
            return Response({"detail": "Listing not found."}, status=status.HTTP_404_NOT_FOUND)
        if not listing.allow_inquiries:
            return Response(
                {"detail": "This listing is not accepting inquiries."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if listing.owner_id == request.user.id:
            return Response(
                {"detail": "You cannot inquire on your own listing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        since = timezone.now() - timedelta(hours=1)
        recent = ListingInquiry.objects.filter(from_user=request.user, created_at__gte=since).count()
        if recent >= 5:
            raise ValidationError({"detail": "Too many inquiries. Please try again later."})

        serializer = ListingInquiryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_email = serializer.validated_data.get("contact_email") or request.user.email or ""
        try:
            conversation, message = send_listing_message(
                listing=listing,
                sender=request.user,
                body=serializer.validated_data["message"],
                buyer_contact_email=contact_email,
                create_legacy_inquiry=True,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        inquiry = ListingInquiry.objects.filter(
            listing=listing,
            from_user=request.user,
            message=message.body,
        ).order_by("-created_at").first()
        payload = ListingInquirySerializer(inquiry).data if inquiry else {}
        payload["conversation_id"] = conversation.id
        payload["message_id"] = message.id
        return Response(payload, status=status.HTTP_201_CREATED)


class MyInquiryListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ListingInquirySerializer
    pagination_class = None

    def get_queryset(self):
        return (
            ListingInquiry.objects.filter(
                listing__owner=self.request.user,
                listing__deleted_at__isnull=True,
            )
            .select_related("listing", "from_user")
        )


class MyInquiryMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        inquiry = ListingInquiry.objects.filter(
            pk=pk,
            listing__owner=request.user,
            listing__deleted_at__isnull=True,
        ).first()
        if not inquiry:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not inquiry.is_read:
            inquiry.is_read = True
            inquiry.save(update_fields=["is_read"])
        return Response(ListingInquirySerializer(inquiry).data)


class PublicListingDocumentSummarizeView(APIView):
    """Ask Terra to summarize a public marketplace listing document."""

    permission_classes = [IsAuthenticated]

    def post(self, request, slug, doc_id):
        listing = _public_queryset().filter(slug=slug).first()
        if not listing:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        document = (
            ListingDocument.objects.filter(pk=doc_id, listing=listing, is_public=True)
            .select_related("listing")
            .first()
        )
        if not document or not document.file:
            return Response({"detail": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

        from apps.analytics.credits import (
            InsufficientAssistantCredits,
            consume_assistant_credit,
            get_assistant_credit_quota,
        )
        from apps.analytics.models import AssistantCreditUsage
        from apps.reports.ai_service import generate_assistant_chat
        from apps.reports.context_extraction import extract_text_from_upload

        try:
            consume_assistant_credit(
                request,
                kind=AssistantCreditUsage.Kind.CHAT,
                user=request.user,
            )
        except InsufficientAssistantCredits as exc:
            return Response(
                {
                    "detail": "No Ask Terra credits remaining.",
                    "assistant_credits": exc.quota,
                    "requires_subscription": exc.quota.get("tier") in ("free", "anonymous"),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        class _NamedUpload:
            def __init__(self, handle, name: str):
                self._handle = handle
                self.name = name

            def read(self, *args, **kwargs):
                return self._handle.read(*args, **kwargs)

            def seek(self, *args, **kwargs):
                return self._handle.seek(*args, **kwargs)

        try:
            with document.file.open("rb") as handle:
                text = extract_text_from_upload(
                    _NamedUpload(handle, document.file.name or document.title or "document.pdf")
                )
        except Exception:
            text = ""

        if not (text or "").strip():
            return Response(
                {
                    "detail": "Could not read text from this document. Try downloading it instead.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        commodities = ", ".join(listing.commodity_labels or []) or "not specified"
        context = (
            "You are Terra, the Terra Meta geological assistant.\n"
            f"Marketplace listing: {listing.title}\n"
            f"Commodities: {commodities}\n"
            f"Listing description: {(listing.description or listing.summary or '').strip() or 'none'}\n"
            f"Document title: {document.title}\n\n"
            "Document text excerpt:\n"
            f"{text.strip()[:12000]}"
        )
        question = (
            "Summarize this marketplace listing document for a mineral exploration buyer. "
            "Highlight geology, commodities, methods, key findings, and any risks or caveats. "
            "Keep it concise and practical."
        )
        reply, model = generate_assistant_chat(
            [{"role": "user", "content": question}],
            context,
            platform_only=False,
        )
        from .analytics import record_listing_event
        from .models import ListingEvent

        record_listing_event(
            listing,
            ListingEvent.Kind.TERRA_SUMMARY,
            user=request.user,
            session_key=getattr(request.session, "session_key", "") or "",
        )
        return Response(
            {
                "summary": reply,
                "ai_model": model,
                "document_id": document.id,
                "document_title": document.title,
                "assistant_credits": get_assistant_credit_quota(request, request.user),
            }
        )


class ParseListingGeometryView(APIView):
    """Parse GeoJSON / shapefile ZIP into a Point or Polygon for a listing AOI."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        _require_profile_complete(request.user)
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Choose a GeoJSON or shapefile ZIP to upload."})
        filename = getattr(upload, "name", "") or "upload.bin"
        lower = filename.lower()
        if not lower.endswith((".geojson", ".json", ".zip", ".shp")):
            raise ValidationError(
                {"file": "Unsupported file type. Upload .geojson, .json, .zip, or .shp."}
            )
        try:
            content = upload.read()
            geometry = geometry_from_upload(content, filename)
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc
        return Response(
            {
                "geometry": geometry,
                "filename": filename,
                "feature_count": _geometry_part_count(geometry),
                "geometry_type": geometry.get("type"),
            }
        )


def _geometry_part_count(geometry: dict) -> int:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point":
        return 1
    if gtype == "MultiPoint":
        return len(coords or [])
    if gtype == "Polygon":
        return 1
    if gtype == "MultiPolygon":
        return len(coords or [])
    if gtype == "GeometryCollection":
        return sum(_geometry_part_count(g) for g in geometry.get("geometries") or [] if isinstance(g, dict))
    return 0

