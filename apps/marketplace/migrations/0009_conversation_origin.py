# Generated manually — track how a conversation started

from django.db import migrations, models


def backfill_conversation_origin(apps, schema_editor):
    ListingConversation = apps.get_model("marketplace", "ListingConversation")
    ListingInquiry = apps.get_model("marketplace", "ListingInquiry")
    ListingMessage = apps.get_model("marketplace", "ListingMessage")

    for conversation in ListingConversation.objects.all().iterator():
        if not conversation.listing_id:
            conversation.origin = "direct"
            conversation.save(update_fields=["origin"])
            continue

        has_inquiry = ListingInquiry.objects.filter(
            listing_id=conversation.listing_id,
            from_user_id=conversation.buyer_id,
        ).exists()
        if has_inquiry:
            conversation.origin = "marketplace_inquiry"
            conversation.save(update_fields=["origin"])
            continue

        first_message = (
            ListingMessage.objects.filter(conversation_id=conversation.id)
            .order_by("created_at")
            .first()
        )
        if first_message and first_message.sender_id == conversation.owner_user_id:
            conversation.origin = "owner_outreach"
        else:
            conversation.origin = "listing_message"
        conversation.save(update_fields=["origin"])


class Migration(migrations.Migration):
    dependencies = [
        (
            "marketplace",
            "0008_rename_marketplace_listing_6d0a8b_idx_marketplace_listing_e2f2d6_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="listingconversation",
            name="origin",
            field=models.CharField(
                choices=[
                    ("marketplace_inquiry", "Marketplace inquiry"),
                    ("listing_message", "Listing message"),
                    ("owner_outreach", "Owner outreach"),
                    ("direct", "Direct message"),
                ],
                default="direct",
                max_length=32,
            ),
        ),
        migrations.RunPython(backfill_conversation_origin, migrations.RunPython.noop),
    ]
