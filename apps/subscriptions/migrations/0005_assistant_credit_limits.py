from django.db import migrations


def update_plan_credits(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(billing_cycle="monthly").update(included_assistant_credits=3000)
    SubscriptionPlan.objects.filter(billing_cycle="annual").update(included_assistant_credits=5000)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0004_assistant_credits"),
    ]

    operations = [
        migrations.RunPython(update_plan_credits, migrations.RunPython.noop),
    ]
