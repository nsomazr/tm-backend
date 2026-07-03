from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0003_report_download_quota"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="included_assistant_credits",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Ask Terra AI credits included per billing period (e.g. 200 monthly, 3000 annual).",
            ),
        ),
    ]
