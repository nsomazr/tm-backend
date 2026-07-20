from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0009_conversation_origin"),
    ]

    operations = [
        migrations.AddField(
            model_name="listingmessage",
            name="reply_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="replies",
                to="marketplace.listingmessage",
            ),
        ),
    ]
