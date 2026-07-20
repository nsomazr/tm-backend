# Generated manually — listing optional on conversations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_owner_user(apps, schema_editor):
    ListingConversation = apps.get_model("marketplace", "ListingConversation")
    for conversation in ListingConversation.objects.select_related("listing").iterator():
        if conversation.listing_id and not conversation.owner_user_id:
            conversation.owner_user_id = conversation.listing.owner_id
            conversation.save(update_fields=["owner_user_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0006_backfill_listing_conversations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="listingconversation",
            name="owner_user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="marketplace_conversations_as_owner",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_owner_user, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="listingconversation",
            name="owner_user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="marketplace_conversations_as_owner",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="listingconversation",
            name="listing",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="conversations",
                to="marketplace.marketplacelisting",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="listingconversation",
            name="uniq_listing_buyer_conversation",
        ),
        migrations.AddConstraint(
            model_name="listingconversation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("listing__isnull", False)),
                fields=("listing", "buyer"),
                name="uniq_listing_buyer_conversation",
            ),
        ),
        migrations.AddConstraint(
            model_name="listingconversation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("listing__isnull", True)),
                fields=("owner_user", "buyer"),
                name="uniq_direct_user_conversation",
            ),
        ),
    ]
