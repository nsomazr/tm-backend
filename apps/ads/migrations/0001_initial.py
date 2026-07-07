import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Ad",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=220, unique=True)),
                ("company_name", models.CharField(max_length=200)),
                ("headline", models.CharField(blank=True, max_length=300)),
                ("body_text", models.TextField(blank=True)),
                ("image", models.ImageField(blank=True, upload_to="ads/")),
                ("cta_label", models.CharField(default="Learn more", max_length=80)),
                ("link_url", models.URLField(max_length=500)),
                ("open_in_new_tab", models.BooleanField(default=True)),
                ("placements", models.JSONField(blank=True, default=list)),
                ("priority", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "is_hidden",
                    models.BooleanField(
                        default=False,
                        help_text="Hide from public surfaces without deleting the campaign.",
                    ),
                ),
                (
                    "audience",
                    models.CharField(
                        choices=[
                            ("all", "All visitors"),
                            ("free", "Free users only"),
                            ("subscriber", "Paid subscribers only"),
                        ],
                        default="all",
                        max_length=20,
                    ),
                ),
                (
                    "country_codes",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="ISO country codes. Empty list means all countries.",
                    ),
                ),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("impression_count", models.PositiveIntegerField(default=0)),
                ("click_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_ads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-priority", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AdEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("impression", "Impression"), ("click", "Click")],
                        max_length=20,
                    ),
                ),
                (
                    "placement",
                    models.CharField(
                        choices=[
                            ("map_sidebar", "Map sidebar"),
                            ("map_overlay", "Map overlay"),
                            ("downloads_banner", "Downloads catalog"),
                            ("subscriptions_banner", "Subscriptions page"),
                            ("dashboard_card", "User dashboard"),
                            ("about_banner", "About page"),
                        ],
                        max_length=40,
                    ),
                ),
                ("session_key", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ad",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="ads.ad",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ad_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["ad", "kind", "created_at"], name="ads_adevent_ad_kind_idx"),
                    models.Index(fields=["placement", "created_at"], name="ads_adevent_place_idx"),
                ],
            },
        ),
    ]
