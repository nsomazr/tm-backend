import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subscriptions", "0003_report_download_quota"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantCreditUsage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, db_index=True, max_length=40)),
                (
                    "kind",
                    models.CharField(
                        choices=[("map_insight", "Map insight"), ("chat", "Chat message")],
                        max_length=20,
                    ),
                ),
                ("credits", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assistant_credit_usages",
                        to="subscriptions.usersubscription",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_credit_usages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="assistantcreditusage",
            index=models.Index(fields=["user", "created_at"], name="analytics_a_user_id_8a0f0d_idx"),
        ),
        migrations.AddIndex(
            model_name="assistantcreditusage",
            index=models.Index(fields=["session_key", "created_at"], name="analytics_a_session_6c2b1a_idx"),
        ),
        migrations.AddIndex(
            model_name="assistantcreditusage",
            index=models.Index(fields=["subscription", "created_at"], name="analytics_a_subscri_4e8f2c_idx"),
        ),
    ]
