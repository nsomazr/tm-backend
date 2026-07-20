from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0010_listingmessage_reply_to"),
    ]

    operations = [
        migrations.AddField(
            model_name="listingconversation",
            name="buyer_archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listingconversation",
            name="owner_archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
