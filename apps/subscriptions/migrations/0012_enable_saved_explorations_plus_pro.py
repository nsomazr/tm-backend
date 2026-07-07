from django.db import migrations


def enable_saved_explorations(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(
        slug__in=["monthly-standard", "annual-standard"],
    ).update(includes_saved_explorations=True)


def disable_saved_explorations(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(
        slug__in=["monthly-standard", "annual-standard"],
    ).update(includes_saved_explorations=False)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0011_alter_subscriptionplan_included_assistant_credits"),
    ]

    operations = [
        migrations.RunPython(enable_saved_explorations, disable_saved_explorations),
    ]
