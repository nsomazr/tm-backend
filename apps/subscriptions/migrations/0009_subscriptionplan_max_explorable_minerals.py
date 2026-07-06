from django.db import migrations, models


def set_default_mineral_limits(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(slug="monthly-standard").update(max_explorable_minerals=10)
    SubscriptionPlan.objects.filter(slug="annual-standard").update(max_explorable_minerals=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0008_subscriptionplan_includes_saved_explorations"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="max_explorable_minerals",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Max unique minerals a subscriber can deep-explore per calendar month. Leave blank for unlimited (11+). Free accounts always get 0.",
                null=True,
            ),
        ),
        migrations.RunPython(set_default_mineral_limits, noop),
    ]
