from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0007_alter_adminboundary_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="adminboundary",
            name="geological_summary",
            field=models.TextField(
                blank=True,
                help_text="Local or regional geological summary for Terra insights (English).",
            ),
        ),
        migrations.AddField(
            model_name="adminboundary",
            name="geological_summary_sw",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="adminboundary",
            name="geological_metadata",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Structured geology: scope, formations, lithology, stratigraphy, age, data_sources.",
            ),
        ),
        migrations.CreateModel(
            name="BoundaryGeologyDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                (
                    "scope",
                    models.CharField(
                        choices=[
                            ("local", "Local"),
                            ("regional", "Regional"),
                            ("global", "Global reference"),
                        ],
                        default="local",
                        max_length=20,
                    ),
                ),
                ("file", models.FileField(upload_to="boundary_geology/")),
                ("extracted_text", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "boundary",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="geology_documents",
                        to="geography.adminboundary",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="boundary_geology_uploads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
