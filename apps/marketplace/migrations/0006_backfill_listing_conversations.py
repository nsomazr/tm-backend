from django.db import migrations


def backfill_conversations(apps, schema_editor):
    ListingInquiry = apps.get_model("marketplace", "ListingInquiry")
    ListingConversation = apps.get_model("marketplace", "ListingConversation")
    ListingMessage = apps.get_model("marketplace", "ListingMessage")

    for inquiry in ListingInquiry.objects.select_related("listing", "from_user").order_by("created_at"):
        conversation, created = ListingConversation.objects.get_or_create(
            listing_id=inquiry.listing_id,
            buyer_id=inquiry.from_user_id,
            defaults={
                "buyer_contact_email": inquiry.contact_email or "",
                "updated_at": inquiry.created_at,
            },
        )
        if not created and inquiry.contact_email and not conversation.buyer_contact_email:
            conversation.buyer_contact_email = inquiry.contact_email
            conversation.save(update_fields=["buyer_contact_email"])
        ListingMessage.objects.get_or_create(
            conversation=conversation,
            sender_id=inquiry.from_user_id,
            body=inquiry.message,
            defaults={"created_at": inquiry.created_at},
        )
        if inquiry.created_at and conversation.updated_at < inquiry.created_at:
            conversation.updated_at = inquiry.created_at
            conversation.save(update_fields=["updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0005_listing_chat_and_notifications"),
    ]

    operations = [
        migrations.RunPython(backfill_conversations, migrations.RunPython.noop),
    ]
