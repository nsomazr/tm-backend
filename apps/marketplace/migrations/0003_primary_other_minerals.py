from django.db import migrations, models


def backfill_primary_other(apps, schema_editor):
    MarketplaceListing = apps.get_model("marketplace", "MarketplaceListing")
    for listing in MarketplaceListing.objects.all().iterator():
        labels = list(listing.commodity_labels or [])
        if not labels:
            continue
        listing.primary_mineral = str(labels[0])[:80]
        listing.other_minerals = [str(item)[:80] for item in labels[1:20]]
        listing.save(update_fields=["primary_mineral", "other_minerals"])


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0002_listing_analytics"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketplacelisting",
            name="primary_mineral",
            field=models.CharField(
                blank=True,
                help_text="Main commodity for this listing (legend / map emphasis).",
                max_length=80,
            ),
        ),
        migrations.AddField(
            model_name="marketplacelisting",
            name="other_minerals",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Additional commodities available on the property.",
            ),
        ),
        migrations.RunPython(backfill_primary_other, migrations.RunPython.noop),
    ]
