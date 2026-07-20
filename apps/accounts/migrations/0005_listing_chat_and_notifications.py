# Generated manually for listing chat

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_rename_accounts_ph_phone_pur_used_idx_accounts_ph_phone_ee60bf_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("marketplace_inquiry", "Marketplace inquiry"),
                            ("marketplace_message", "Marketplace message"),
                        ],
                        max_length=40,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField(blank=True)),
                ("link", models.CharField(blank=True, max_length=500)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(fields=["user", "is_read", "created_at"], name="accounts_us_user_id_8a0d0d_idx"),
        ),
    ]
