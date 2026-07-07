from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0009_alter_assistantcreditusage_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantPlatformSettings",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
                ("ai_provider", models.CharField(blank=True, default="", max_length=20)),
                ("ai_provider_fallback", models.CharField(blank=True, default="", max_length=120)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Assistant platform settings",
                "verbose_name_plural": "Assistant platform settings",
            },
        ),
    ]
