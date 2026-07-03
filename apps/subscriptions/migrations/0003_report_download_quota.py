from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subscriptions", "0002_remove_pesapal_account_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="included_report_downloads",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="PDF downloads included per billing period (e.g. 3 monthly, 10 annual).",
            ),
        ),
        migrations.CreateModel(
            name="SubscriptionReportDownload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("downloaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_downloads",
                        to="reports.report",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_downloads",
                        to="subscriptions.usersubscription",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_report_downloads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("user", "report", "subscription")},
            },
        ),
    ]
