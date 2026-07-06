from decimal import Decimal

from django.db import migrations


def update_prices(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    updates = {
        "monthly-starter": Decimal("50000"),
        "monthly-standard": Decimal("100000"),
        "annual-standard": Decimal("1800000"),
    }
    for slug, price in updates.items():
        SubscriptionPlan.objects.filter(slug=slug).update(price=price)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0009_subscriptionplan_max_explorable_minerals"),
    ]

    operations = [
        migrations.RunPython(update_prices, migrations.RunPython.noop),
    ]
