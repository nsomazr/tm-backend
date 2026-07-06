import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subscriptions", "0009_subscriptionplan_max_explorable_minerals"),
        ("analytics", "0006_alter_assistantcreditusage_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="MineralExplorationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mineral_slug", models.SlugField(max_length=220)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mineral_exploration_logs",
                        to="subscriptions.usersubscription",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mineral_exploration_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["user", "mineral_slug", "created_at"], name="analytics_m_user_id_4b0d0a_idx"),
                    models.Index(fields=["user", "created_at"], name="analytics_m_user_id_8f2c1d_idx"),
                ],
            },
        ),
    ]
