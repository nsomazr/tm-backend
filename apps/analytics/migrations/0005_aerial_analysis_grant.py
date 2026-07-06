import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_remove_selcom_provider"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("analytics", "0004_rename_analytics_a_user_id_chat_idx_analytics_a_user_id_390eaa_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="AerialAnalysisGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("lat", models.FloatField()),
                ("lng", models.FloatField()),
                ("zoom", models.PositiveSmallIntegerField(default=8)),
                ("max_area_km2", models.FloatField()),
                ("purchased_extra_km2", models.FloatField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "payment_order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="aerial_grants",
                        to="payments.paymentorder",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aerial_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
