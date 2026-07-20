# Generated manually for listing chat

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0004_alter_commodity_labels_help"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ListingConversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("buyer_contact_email", models.EmailField(blank=True, max_length=254)),
                ("owner_last_read_at", models.DateTimeField(blank=True, null=True)),
                ("buyer_last_read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketplace_conversations_as_buyer",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversations",
                        to="marketplace.marketplacelisting",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="ListingMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="marketplace.listingconversation",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marketplace_messages_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="listingconversation",
            constraint=models.UniqueConstraint(
                fields=("listing", "buyer"),
                name="uniq_listing_buyer_conversation",
            ),
        ),
        migrations.AddIndex(
            model_name="listingconversation",
            index=models.Index(fields=["listing", "updated_at"], name="marketplace_listing_6d0a8b_idx"),
        ),
        migrations.AddIndex(
            model_name="listingconversation",
            index=models.Index(fields=["buyer", "updated_at"], name="marketplace_buyer_i_5f0d1a_idx"),
        ),
        migrations.AddIndex(
            model_name="listingmessage",
            index=models.Index(fields=["conversation", "created_at"], name="marketplace_convers_0b0f2c_idx"),
        ),
    ]
