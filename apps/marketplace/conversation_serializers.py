from rest_framework import serializers

from .models import ListingConversation, ListingMessage


class ListingMessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source="sender.username", read_only=True)
    is_mine = serializers.SerializerMethodField()
    read_by_recipient = serializers.SerializerMethodField()
    reply_to = serializers.SerializerMethodField()

    class Meta:
        model = ListingMessage
        fields = (
            "id",
            "sender",
            "sender_username",
            "body",
            "reply_to",
            "created_at",
            "is_mine",
            "read_by_recipient",
        )
        read_only_fields = fields

    def get_reply_to(self, obj: ListingMessage):
        if not obj.reply_to_id:
            return None
        target = obj.reply_to
        return {
            "id": target.id,
            "sender_username": target.sender.username,
            "body": target.body,
        }

    def get_is_mine(self, obj: ListingMessage) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.is_authenticated and obj.sender_id == request.user.id)

    def get_read_by_recipient(self, obj: ListingMessage) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated or obj.sender_id != request.user.id:
            return False
        conversation = obj.conversation
        if obj.sender_id == conversation.owner_user_id:
            read_at = conversation.buyer_last_read_at
        else:
            read_at = conversation.owner_last_read_at
        if not read_at:
            return False
        return read_at >= obj.created_at


class ListingMessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)
    reply_to_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_body(self, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 10:
            raise serializers.ValidationError("Message must be at least 10 characters.")
        return text


class ListingConversationSerializer(serializers.ModelSerializer):
    listing_title = serializers.SerializerMethodField()
    listing_slug = serializers.SerializerMethodField()
    buyer_username = serializers.CharField(source="buyer.username", read_only=True)
    owner_username = serializers.CharField(source="owner_user.username", read_only=True)
    last_message = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()
    archived = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = ListingConversation
        fields = (
            "id",
            "listing",
            "listing_title",
            "listing_slug",
            "buyer",
            "buyer_username",
            "owner_username",
            "buyer_contact_email",
            "owner_last_read_at",
            "buyer_last_read_at",
            "last_message",
            "unread",
            "archived",
            "role",
            "origin",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_listing_title(self, obj: ListingConversation) -> str | None:
        return obj.listing.title if obj.listing_id else None

    def get_listing_slug(self, obj: ListingConversation) -> str | None:
        return obj.listing.slug if obj.listing_id else None

    def get_last_message(self, obj: ListingConversation):
        message = obj.messages.order_by("-created_at").first()
        if not message:
            return None
        return ListingMessageSerializer(message, context=self.context).data

    def get_unread(self, obj: ListingConversation) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        from .conversation_service import conversation_unread_for_user

        return conversation_unread_for_user(obj, request.user)

    def get_archived(self, obj: ListingConversation) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        from .conversation_service import conversation_archived_for_user

        return conversation_archived_for_user(obj, request.user)

    def get_role(self, obj: ListingConversation) -> str:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return "viewer"
        if request.user.id == obj.owner_user_id:
            return "owner"
        if request.user.id == obj.buyer_id:
            return "buyer"
        return "viewer"


class ListingConversationDetailSerializer(ListingConversationSerializer):
    messages = serializers.SerializerMethodField()

    class Meta(ListingConversationSerializer.Meta):
        fields = ListingConversationSerializer.Meta.fields + ("messages",)

    def get_messages(self, obj: ListingConversation):
        qs = (
            obj.messages.select_related("sender", "conversation", "reply_to", "reply_to__sender")
            .order_by("created_at")
        )
        return ListingMessageSerializer(qs, many=True, context=self.context).data
