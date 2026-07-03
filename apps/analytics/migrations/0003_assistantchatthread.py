import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("analytics", "0002_rename_analytics_a_user_id_8a0f0d_idx_analytics_a_user_id_3d5425_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantChatThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("thread_key", models.CharField(max_length=120)),
                ("messages", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_chat_threads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="assistantchatthread",
            index=models.Index(fields=["user", "thread_key"], name="analytics_a_user_id_chat_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="assistantchatthread",
            unique_together={("user", "thread_key")},
        ),
    ]
