from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserNotification

from .email_templates import (
    marketplace_inquiry_html,
    marketplace_inquiry_text,
    marketplace_message_html,
    marketplace_message_text,
)
from .models import ListingConversation, ListingInquiry, ListingMessage, MarketplaceListing

logger = logging.getLogger(__name__)

MESSAGE_MIN_LEN = 10
MESSAGE_MAX_LEN = 4000


def _validate_body(body: str) -> str:
    text = (body or "").strip()
    if len(text) < MESSAGE_MIN_LEN:
        raise ValueError("Message must be at least 10 characters.")
    if len(text) > MESSAGE_MAX_LEN:
        raise ValueError("Message is too long.")
    return text


def _dashboard_messages_link(conversation_id: int) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/dashboard/marketplace/messages?conversation={conversation_id}"


def _listing_messages_link(slug: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/marketplace?listing={slug}"


def _listing_public_url(slug: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/marketplace?listing={slug}"


def _resolve_conversation_origin(
    *,
    listing: MarketplaceListing | None,
    is_owner: bool,
    create_legacy_inquiry: bool,
) -> str:
    if not listing:
        return ListingConversation.Origin.DIRECT
    if create_legacy_inquiry and not is_owner:
        return ListingConversation.Origin.MARKETPLACE_INQUIRY
    if is_owner:
        return ListingConversation.Origin.OWNER_OUTREACH
    return ListingConversation.Origin.LISTING_MESSAGE


def _owner_notify_email(listing: MarketplaceListing) -> str:
    contact = (listing.contact_email or "").strip()
    if contact:
        return contact
    return (listing.owner.email or "").strip()


def _buyer_notify_email(conversation: ListingConversation) -> str:
    contact = (conversation.buyer_contact_email or "").strip()
    if contact:
        return contact
    return (conversation.buyer.email or "").strip()


def _participant_notify_email(user) -> str:
    return (user.email or "").strip()


def _direct_participant_ids(user_a_id: int, user_b_id: int) -> tuple[int, int]:
    if user_a_id < user_b_id:
        return user_a_id, user_b_id
    return user_b_id, user_a_id


def _conversation_recipient(conversation: ListingConversation, sender) -> tuple[object, str]:
    if sender.id == conversation.buyer_id:
        return conversation.owner_user, _participant_notify_email(conversation.owner_user)
    if sender.id == conversation.owner_user_id:
        return conversation.buyer, _buyer_notify_email(conversation)
    raise ValueError("You are not part of this conversation.")


def _create_platform_notification(
    *,
    user,
    kind: str,
    title: str,
    body: str,
    link: str,
    payload: dict | None = None,
) -> UserNotification:
    return UserNotification.objects.create(
        user=user,
        kind=kind,
        title=title,
        body=body,
        link=link,
        payload=payload or {},
    )


def _send_marketplace_email(
    *,
    to_email: str,
    subject: str,
    heading: str,
    intro: str,
    listing_title: str = "",
    message_preview: str,
    action_label: str,
    action_url: str,
) -> None:
    if not to_email:
        return
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=marketplace_message_text(
                heading=heading,
                intro=intro,
                listing_title=listing_title,
                message_preview=message_preview,
                action_label=action_label,
                action_url=action_url,
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(
            marketplace_message_html(
                heading=heading,
                intro=intro,
                listing_title=listing_title,
                message_preview=message_preview,
                action_label=action_label,
                action_url=action_url,
            ),
            "text/html",
        )
        msg.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send marketplace email to %s", to_email)


def _send_inquiry_email(
    *,
    to_email: str,
    subject: str,
    heading: str,
    listing_title: str,
    sender,
    buyer_contact_email: str,
    message_preview: str,
    inbox_url: str,
    listing_url: str,
) -> None:
    if not to_email:
        return
    sender_name = (sender.get_full_name() or "").strip() or sender.get_username()
    sender_email = (buyer_contact_email or sender.email or "").strip()
    sender_organization = getattr(sender, "organization", "") or ""
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=marketplace_inquiry_text(
                heading=heading,
                listing_title=listing_title,
                sender_name=sender_name,
                sender_username=sender.get_username(),
                sender_email=sender_email,
                sender_organization=sender_organization,
                message_preview=message_preview,
                inbox_url=inbox_url,
                listing_url=listing_url,
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(
            marketplace_inquiry_html(
                heading=heading,
                listing_title=listing_title,
                sender_name=sender_name,
                sender_username=sender.get_username(),
                sender_email=sender_email,
                sender_organization=sender_organization,
                message_preview=message_preview,
                inbox_url=inbox_url,
                listing_url=listing_url,
            ),
            "text/html",
        )
        msg.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send marketplace inquiry email to %s", to_email)


def conversation_unread_for_user(conversation: ListingConversation, user) -> bool:
    if user.id == conversation.owner_user_id:
        since = conversation.owner_last_read_at
        other_id = conversation.buyer_id
    elif user.id == conversation.buyer_id:
        since = conversation.buyer_last_read_at
        other_id = conversation.owner_user_id
    else:
        return False
    qs = conversation.messages.filter(sender_id=other_id)
    if since:
        qs = qs.filter(created_at__gt=since)
    return qs.exists()


def conversation_archived_for_user(conversation: ListingConversation, user) -> bool:
    if user.id == conversation.owner_user_id:
        return conversation.owner_archived_at is not None
    if user.id == conversation.buyer_id:
        return conversation.buyer_archived_at is not None
    return False


def set_conversation_archived(
    *,
    conversation: ListingConversation,
    user,
    archived: bool,
) -> ListingConversation:
    if user.id not in {conversation.buyer_id, conversation.owner_user_id}:
        raise ValueError("You are not part of this conversation.")
    if user.id == conversation.owner_user_id:
        conversation.owner_archived_at = timezone.now() if archived else None
        conversation.save(update_fields=["owner_archived_at", "updated_at"])
    else:
        conversation.buyer_archived_at = timezone.now() if archived else None
        conversation.save(update_fields=["buyer_archived_at", "updated_at"])
    return conversation


def mark_conversation_read(conversation: ListingConversation, user) -> None:
    now = timezone.now()
    if user.id == conversation.owner_user_id:
        conversation.owner_last_read_at = now
        conversation.save(update_fields=["owner_last_read_at", "updated_at"])
    elif user.id == conversation.buyer_id:
        conversation.buyer_last_read_at = now
        conversation.save(update_fields=["buyer_last_read_at", "updated_at"])


def _resolve_reply_to(
    conversation: ListingConversation,
    reply_to_id: int | None,
) -> ListingMessage | None:
    if not reply_to_id:
        return None
    reply = ListingMessage.objects.filter(
        pk=reply_to_id,
        conversation_id=conversation.id,
    ).first()
    if not reply:
        raise ValueError("Reply target not found in this conversation.")
    return reply


def _append_conversation_message(
    *,
    conversation: ListingConversation,
    sender,
    body: str,
    reply_to: ListingMessage | None = None,
) -> ListingMessage:
    text = _validate_body(body)
    message = ListingMessage.objects.create(
        conversation=conversation,
        sender=sender,
        body=text,
        reply_to=reply_to,
    )
    conversation.updated_at = message.created_at
    update_fields = ["updated_at"]
    if sender.id == conversation.owner_user_id and conversation.buyer_archived_at is not None:
        conversation.buyer_archived_at = None
        update_fields.append("buyer_archived_at")
    elif sender.id == conversation.buyer_id and conversation.owner_archived_at is not None:
        conversation.owner_archived_at = None
        update_fields.append("owner_archived_at")
    conversation.save(update_fields=update_fields)

    listing = conversation.listing if conversation.listing_id else None
    preview = text if len(text) <= 280 else f"{text[:277]}…"
    _notify_message_sent(
        conversation=conversation,
        sender=sender,
        preview=preview,
        listing=listing,
        is_first_message=conversation.messages.count() == 1,
    )
    return message


def _notify_message_sent(
    *,
    conversation: ListingConversation,
    sender,
    preview: str,
    listing: MarketplaceListing | None,
    is_first_message: bool,
) -> None:
    listing_title = listing.title if listing else ""
    dashboard_link = _dashboard_messages_link(conversation.id)
    listing_link = _listing_messages_link(listing.slug) if listing else dashboard_link
    listing_public_url = _listing_public_url(listing.slug) if listing else dashboard_link
    is_marketplace_inquiry = (
        is_first_message
        and conversation.origin == ListingConversation.Origin.MARKETPLACE_INQUIRY
    )

    if listing and sender.id == listing.owner_id:
        recipient = conversation.buyer
        notify_email = _buyer_notify_email(conversation)
        title = (
            f"Message about {listing_title}"
            if is_first_message
            else f"New reply on {listing_title}"
        )
        intro = (
            f"The owner of <strong>{listing_title}</strong> sent you a message on Terra Meta."
            if is_first_message
            else f"The owner of <strong>{listing_title}</strong> replied to your inquiry."
        )
        action_url = listing_link
        action_label = "View conversation"
        payload = {
            "conversation_id": conversation.id,
            "listing_id": listing.id,
            "listing_slug": listing.slug,
        }
    elif listing:
        recipient = listing.owner
        notify_email = _owner_notify_email(listing)
        kind = (
            UserNotification.Kind.MARKETPLACE_INQUIRY
            if is_marketplace_inquiry
            else UserNotification.Kind.MARKETPLACE_MESSAGE
        )
        title = (
            f"New inquiry on {listing_title}"
            if kind == UserNotification.Kind.MARKETPLACE_INQUIRY
            else f"New message on {listing_title}"
        )
        intro = (
            f"<strong>{sender.get_username()}</strong> sent an inquiry about <strong>{listing_title}</strong> from the public marketplace."
            if kind == UserNotification.Kind.MARKETPLACE_INQUIRY
            else f"<strong>{sender.get_username()}</strong> sent a follow-up about <strong>{listing_title}</strong>."
        )
        action_url = dashboard_link
        action_label = "Open inbox"
        payload = {
            "conversation_id": conversation.id,
            "listing_id": listing.id,
            "listing_slug": listing.slug,
            "from_user_id": sender.id,
            "origin": conversation.origin,
        }
        _create_platform_notification(
            user=recipient,
            kind=kind,
            title=title,
            body=preview,
            link=dashboard_link,
            payload=payload,
        )
        if is_marketplace_inquiry:
            _send_inquiry_email(
                to_email=notify_email,
                subject=title,
                heading=title,
                listing_title=listing_title,
                sender=sender,
                buyer_contact_email=conversation.buyer_contact_email,
                message_preview=preview,
                inbox_url=dashboard_link,
                listing_url=listing_public_url,
            )
        else:
            _send_marketplace_email(
                to_email=notify_email,
                subject=title,
                heading=title,
                intro=intro,
                listing_title=listing_title,
                message_preview=preview,
                action_label=action_label,
                action_url=action_url,
            )
        return
    else:
        recipient, notify_email = _conversation_recipient(conversation, sender)
        username = sender.get_username()
        title = f"New message from {username}" if is_first_message else f"New reply from {username}"
        intro = (
            f"<strong>{username}</strong> sent you a message on Terra Meta."
            if is_first_message
            else f"<strong>{username}</strong> replied to your conversation."
        )
        action_url = dashboard_link
        action_label = "Open inbox"
        payload = {
            "conversation_id": conversation.id,
            "from_user_id": sender.id,
            "origin": conversation.origin,
        }

    _create_platform_notification(
        user=recipient,
        kind=UserNotification.Kind.MARKETPLACE_MESSAGE,
        title=title,
        body=preview,
        link=action_url,
        payload=payload,
    )
    _send_marketplace_email(
        to_email=notify_email,
        subject=title,
        heading=title,
        intro=intro,
        listing_title=listing_title,
        message_preview=preview,
        action_label=action_label,
        action_url=action_url,
    )


@transaction.atomic
def send_direct_message(
    *,
    sender,
    recipient,
    body: str,
) -> tuple[ListingConversation, ListingMessage]:
    if sender.id == recipient.id:
        raise ValueError("You cannot message yourself.")
    text = _validate_body(body)
    owner_id, buyer_id = _direct_participant_ids(sender.id, recipient.id)
    conversation, created = ListingConversation.objects.select_for_update().get_or_create(
        listing=None,
        owner_user_id=owner_id,
        buyer_id=buyer_id,
        defaults={
            "buyer_contact_email": "",
            "origin": ListingConversation.Origin.DIRECT,
        },
    )
    if created and conversation.buyer.email:
        conversation.buyer_contact_email = conversation.buyer.email
        conversation.save(update_fields=["buyer_contact_email", "updated_at"])
    elif not conversation.buyer_contact_email and conversation.buyer.email:
        conversation.buyer_contact_email = conversation.buyer.email
        conversation.save(update_fields=["buyer_contact_email", "updated_at"])

    message = ListingMessage.objects.create(
        conversation=conversation,
        sender=sender,
        body=text,
    )
    conversation.updated_at = message.created_at
    conversation.save(update_fields=["updated_at"])

    preview = text if len(text) <= 280 else f"{text[:277]}…"
    _notify_message_sent(
        conversation=conversation,
        sender=sender,
        preview=preview,
        listing=None,
        is_first_message=conversation.messages.count() == 1,
    )
    return conversation, message


@transaction.atomic
def send_listing_message(
    *,
    listing: MarketplaceListing,
    sender,
    body: str,
    buyer=None,
    buyer_contact_email: str = "",
    create_legacy_inquiry: bool = False,
) -> tuple[ListingConversation, ListingMessage]:
    text = _validate_body(body)
    is_owner = sender.id == listing.owner_id

    if is_owner:
        if buyer is None:
            raise ValueError("Buyer is required when the owner replies.")
        origin = ListingConversation.Origin.OWNER_OUTREACH
        conversation, created = ListingConversation.objects.select_for_update().get_or_create(
            listing=listing,
            buyer=buyer,
            defaults={
                "buyer_contact_email": buyer.email or "",
                "owner_user_id": listing.owner_id,
                "origin": origin,
            },
        )
        if not created and conversation.owner_user_id != listing.owner_id:
            conversation.owner_user_id = listing.owner_id
            conversation.save(update_fields=["owner_user_id", "updated_at"])
        if not created and not conversation.buyer_contact_email and buyer.email:
            conversation.buyer_contact_email = buyer.email
            conversation.save(update_fields=["buyer_contact_email", "updated_at"])
    else:
        if listing.owner_id == sender.id:
            raise ValueError("You cannot message your own listing.")
        origin = _resolve_conversation_origin(
            listing=listing,
            is_owner=False,
            create_legacy_inquiry=create_legacy_inquiry,
        )
        conversation, _created = ListingConversation.objects.select_for_update().get_or_create(
            listing=listing,
            buyer=sender,
            defaults={
                "buyer_contact_email": buyer_contact_email or sender.email or "",
                "owner_user_id": listing.owner_id,
                "origin": origin,
            },
        )
        if create_legacy_inquiry and conversation.origin != ListingConversation.Origin.MARKETPLACE_INQUIRY:
            conversation.origin = ListingConversation.Origin.MARKETPLACE_INQUIRY
            conversation.save(update_fields=["origin", "updated_at"])
        if buyer_contact_email and conversation.buyer_contact_email != buyer_contact_email:
            conversation.buyer_contact_email = buyer_contact_email
            conversation.save(update_fields=["buyer_contact_email", "updated_at"])

    message = ListingMessage.objects.create(
        conversation=conversation,
        sender=sender,
        body=text,
    )
    conversation.updated_at = message.created_at
    conversation.save(update_fields=["updated_at"])

    if create_legacy_inquiry and not is_owner:
        ListingInquiry.objects.create(
            listing=listing,
            from_user=sender,
            message=text,
            contact_email=buyer_contact_email or sender.email or "",
            is_read=False,
        )

    preview = text if len(text) <= 280 else f"{text[:277]}…"
    _notify_message_sent(
        conversation=conversation,
        sender=sender,
        preview=preview,
        listing=listing,
        is_first_message=conversation.messages.count() == 1,
    )

    return conversation, message


@transaction.atomic
def send_conversation_message(
    *,
    conversation: ListingConversation,
    sender,
    body: str,
    reply_to_id: int | None = None,
) -> tuple[ListingConversation, ListingMessage]:
    if sender.id not in {conversation.buyer_id, conversation.owner_user_id}:
        raise ValueError("You are not part of this conversation.")
    reply_to = _resolve_reply_to(conversation, reply_to_id)
    if conversation.listing_id:
        listing = conversation.listing
        if sender.id != listing.owner_id and not listing.allow_inquiries:
            raise ValueError("This listing is not accepting inquiries.")
        message = _append_conversation_message(
            conversation=conversation,
            sender=sender,
            body=body,
            reply_to=reply_to,
        )
        return conversation, message
    message = _append_conversation_message(
        conversation=conversation,
        sender=sender,
        body=body,
        reply_to=reply_to,
    )
    return conversation, message


@transaction.atomic
def delete_conversation(*, conversation: ListingConversation, user) -> None:
    if user.id not in {conversation.buyer_id, conversation.owner_user_id}:
        raise ValueError("You are not part of this conversation.")
    conversation.delete()


@transaction.atomic
def delete_conversation_message(
    *,
    conversation: ListingConversation,
    message_id: int,
    user,
) -> ListingConversation:
    if user.id not in {conversation.buyer_id, conversation.owner_user_id}:
        raise ValueError("You are not part of this conversation.")
    message = ListingMessage.objects.filter(
        pk=message_id,
        conversation_id=conversation.id,
    ).first()
    if not message:
        raise ValueError("Message not found.")
    if message.sender_id != user.id:
        raise ValueError("You can only delete your own messages.")
    message.delete()
    latest = conversation.messages.order_by("-created_at").first()
    conversation.updated_at = latest.created_at if latest else conversation.created_at
    conversation.save(update_fields=["updated_at"])
    return conversation
