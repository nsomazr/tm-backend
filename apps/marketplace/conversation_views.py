from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .conversation_serializers import (
    ListingConversationDetailSerializer,
    ListingConversationSerializer,
    ListingMessageCreateSerializer,
    ListingMessageSerializer,
)
from .conversation_service import (
    delete_conversation,
    delete_conversation_message,
    mark_conversation_read,
    send_conversation_message,
    send_direct_message,
    send_listing_message,
    set_conversation_archived,
)
from .models import ListingConversation, ListingMessage, MarketplaceListing
from .views import _owner_queryset, _public_queryset

User = get_user_model()


class MarketplaceUserSearchResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    organization = serializers.CharField()
    public_listing_count = serializers.IntegerField()


class ConversationListingOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    slug = serializers.CharField()
    role = serializers.ChoiceField(choices=["owner", "buyer"])


class StartConversationSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField(required=False, allow_null=True)
    recipient_user_id = serializers.IntegerField()
    message = serializers.CharField(max_length=4000)

    def validate_message(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 10:
            raise serializers.ValidationError("Message must be at least 10 characters.")
        return text


class MarketplaceUserSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response([])

        users = (
            User.objects.filter(is_active=True, profile_complete=True)
            .exclude(pk=request.user.pk)
            .filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(organization__icontains=query)
            )
            .order_by("username")[:12]
        )

        public_counts = {
            row["owner_id"]: row["count"]
            for row in _public_queryset()
            .filter(owner_id__in=[user.id for user in users])
            .values("owner_id")
            .annotate(count=models.Count("id"))
        }

        payload = [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.get_full_name().strip() or user.username,
                "organization": user.organization or "",
                "public_listing_count": public_counts.get(user.id, 0),
            }
            for user in users
        ]
        return Response(MarketplaceUserSearchResultSerializer(payload, many=True).data)


class ConversationListingOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            target_id = int(request.query_params.get("user_id") or "")
        except (TypeError, ValueError):
            raise ValidationError({"user_id": "Choose a registered user."}) from None

        target = User.objects.filter(pk=target_id, is_active=True, profile_complete=True).first()
        if not target or target.id == request.user.id:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        options = []

        for listing in _owner_queryset(request.user).filter(status=MarketplaceListing.Status.PUBLISHED):
            options.append(
                {
                    "id": listing.id,
                    "title": listing.title,
                    "slug": listing.slug,
                    "role": "owner",
                }
            )

        for listing in _public_queryset().filter(owner=target):
            if not listing.allow_inquiries:
                continue
            options.append(
                {
                    "id": listing.id,
                    "title": listing.title,
                    "slug": listing.slug,
                    "role": "buyer",
                }
            )

        return Response(ConversationListingOptionSerializer(options, many=True).data)


class StartConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        recipient = User.objects.filter(
            pk=serializer.validated_data["recipient_user_id"],
            is_active=True,
            profile_complete=True,
        ).first()
        if not recipient or recipient.id == request.user.id:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        message = serializer.validated_data["message"]
        listing_id = serializer.validated_data.get("listing_id")

        if listing_id:
            listing = (
                MarketplaceListing.objects.filter(pk=listing_id, deleted_at__isnull=True)
                .select_related("owner")
                .first()
            )
            if not listing:
                return Response({"detail": "Listing not found."}, status=status.HTTP_404_NOT_FOUND)

            try:
                if listing.owner_id == request.user.id:
                    conversation, _ = send_listing_message(
                        listing=listing,
                        sender=request.user,
                        body=message,
                        buyer=recipient,
                    )
                elif listing.owner_id == recipient.id and listing.allow_inquiries:
                    conversation, _ = send_listing_message(
                        listing=listing,
                        sender=request.user,
                        body=message,
                        buyer_contact_email=request.user.email or "",
                        create_legacy_inquiry=True,
                    )
                else:
                    return Response(
                        {"detail": "You cannot start a conversation for this listing."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except ValueError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
        else:
            try:
                conversation, _ = send_direct_message(
                    sender=request.user,
                    recipient=recipient,
                    body=message,
                )
            except ValueError as exc:
                raise ValidationError({"detail": str(exc)}) from exc

        mark_conversation_read(conversation, request.user)
        return Response(
            ListingConversationDetailSerializer(conversation, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


def _conversation_queryset(user, *, archived: bool | None = None):
    qs = (
        ListingConversation.objects.filter(
            models.Q(listing__isnull=True) | models.Q(listing__deleted_at__isnull=True),
        )
        .filter(
            models.Q(owner_user=user) | models.Q(buyer=user),
        )
        .select_related("listing", "listing__owner", "owner_user", "buyer")
        .prefetch_related("messages__sender", "messages__reply_to", "messages__reply_to__sender")
    )
    if archived is True:
        return qs.filter(
            models.Q(owner_user=user, owner_archived_at__isnull=False)
            | models.Q(buyer=user, buyer_archived_at__isnull=False)
        )
    if archived is False:
        return qs.exclude(
            models.Q(owner_user=user, owner_archived_at__isnull=False)
            | models.Q(buyer=user, buyer_archived_at__isnull=False)
        )
    return qs


class MyConversationListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ListingConversationSerializer
    pagination_class = None

    def get_queryset(self):
        archived_param = self.request.query_params.get("archived")
        if archived_param == "1":
            archived = True
        elif archived_param == "all":
            archived = None
        else:
            archived = False
        return _conversation_queryset(self.request.user, archived=archived)


class MyConversationDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ListingConversationDetailSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return _conversation_queryset(self.request.user, archived=None)

    def retrieve(self, request, *args, **kwargs):
        conversation = self.get_object()
        mark_conversation_read(conversation, request.user)
        serializer = self.get_serializer(conversation)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        conversation = self.get_object()
        try:
            delete_conversation(conversation=conversation, user=request.user)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyConversationMessageCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _conversation_queryset(request.user, archived=None).filter(pk=pk).first()
        if not conversation:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ListingMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            _, message = send_conversation_message(
                conversation=conversation,
                sender=request.user,
                body=serializer.validated_data["body"],
                reply_to_id=serializer.validated_data.get("reply_to_id"),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        mark_conversation_read(conversation, request.user)
        conversation.refresh_from_db()
        return Response(
            {
                "conversation": ListingConversationDetailSerializer(
                    conversation,
                    context={"request": request},
                ).data,
                "message": ListingMessageSerializer(message, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class MyConversationMessageDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, message_id):
        conversation = _conversation_queryset(request.user, archived=None).filter(pk=pk).first()
        if not conversation:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            conversation = delete_conversation_message(
                conversation=conversation,
                message_id=message_id,
                user=request.user,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        conversation.refresh_from_db()
        return Response(
            ListingConversationDetailSerializer(conversation, context={"request": request}).data
        )


class MyConversationArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _conversation_queryset(request.user, archived=None).filter(pk=pk).first()
        if not conversation:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        archived = request.data.get("archived", True)
        if not isinstance(archived, bool):
            raise ValidationError({"archived": "Must be true or false."})

        try:
            conversation = set_conversation_archived(
                conversation=conversation,
                user=request.user,
                archived=archived,
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return Response(
            ListingConversationSerializer(conversation, context={"request": request}).data
        )


class MyConversationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        conversation = _conversation_queryset(request.user, archived=None).filter(pk=pk).first()
        if not conversation:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        mark_conversation_read(conversation, request.user)
        return Response(
            ListingConversationSerializer(conversation, context={"request": request}).data
        )


class ListingConversationForBuyerView(APIView):
    """Return the signed-in buyer's conversation for a public listing, if any."""

    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        listing = _public_queryset().filter(slug=slug).first()
        if not listing:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        conversation = (
            ListingConversation.objects.filter(listing=listing, buyer=request.user)
            .select_related("listing", "listing__owner", "buyer")
            .prefetch_related("messages__sender", "messages__reply_to", "messages__reply_to__sender")
            .first()
        )
        if not conversation:
            return Response({"conversation": None})
        mark_conversation_read(conversation, request.user)
        return Response(
            {
                "conversation": ListingConversationDetailSerializer(
                    conversation,
                    context={"request": request},
                ).data,
            }
        )
