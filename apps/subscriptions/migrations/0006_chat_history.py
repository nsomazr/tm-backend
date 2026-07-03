from django.db import migrations, models


def enable_chat_history_on_paid_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model("subscriptions", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(billing_cycle__in=["monthly", "annual"]).update(
        includes_chat_history=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0005_assistant_credit_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="includes_chat_history",
            field=models.BooleanField(
                default=False,
                help_text="Subscribers can persist Ask Terra chat threads across sessions.",
            ),
        ),
        migrations.RunPython(enable_chat_history_on_paid_plans, migrations.RunPython.noop),
    ]
