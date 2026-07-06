# Generated manually for reports module expansion

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_report_defaults(apps, schema_editor):
    Report = apps.get_model("reports", "Report")
    for report in Report.objects.all():
        updates = {}
        if not report.source_type:
            if report.pdf_file:
                updates["source_type"] = "uploaded"
            else:
                updates["source_type"] = "ai_generated"
        if not report.access_type:
            updates["access_type"] = "paid"
        if not report.report_format:
            updates["report_format"] = "pdf"
        if updates:
            Report.objects.filter(pk=report.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0001_initial"),
        ("maps", "0009_deactivate_placeholder_layers"),
        ("minerals", "0001_initial"),
        ("subscriptions", "0010_update_plan_prices"),
        ("reports", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("uploaded", "Uploaded"),
                    ("ai_generated", "AI generated"),
                    ("user_generated", "User generated"),
                ],
                default="ai_generated",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="access_type",
            field=models.CharField(
                choices=[
                    ("free", "Free"),
                    ("paid", "Paid"),
                    ("subscriber_only", "Subscriber only"),
                    ("subscriber_or_paid", "Subscriber or paid"),
                ],
                default="paid",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="report_format",
            field=models.CharField(
                choices=[
                    ("pdf", "PDF"),
                    ("web_article", "Web article"),
                    ("pdf_and_article", "PDF and web article"),
                ],
                default="pdf",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="center_lat",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="report",
            name="center_lng",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="report",
            name="zoom",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="report",
            name="article_body",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="report",
            name="allowed_plans",
            field=models.ManyToManyField(
                blank=True,
                related_name="gated_reports",
                to="subscriptions.subscriptionplan",
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="layers",
            field=models.ManyToManyField(
                blank=True,
                related_name="linked_reports",
                to="maps.maplayer",
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="boundaries",
            field=models.ManyToManyField(
                blank=True,
                related_name="linked_reports",
                to="geography.adminboundary",
            ),
        ),
        migrations.CreateModel(
            name="ReportDocumentChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("page_number", models.PositiveIntegerField(default=1)),
                ("chunk_index", models.PositiveIntegerField(default=0)),
                ("text", models.TextField()),
                ("embedding", models.JSONField(blank=True, default=list)),
                ("token_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="document_chunks",
                        to="reports.report",
                    ),
                ),
            ],
            options={
                "ordering": ["page_number", "chunk_index"],
            },
        ),
        migrations.CreateModel(
            name="ReportChatThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("messages", models.JSONField(blank=True, default=list)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_threads",
                        to="reports.report",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_chat_threads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
                "unique_together": {("report", "user")},
            },
        ),
        migrations.CreateModel(
            name="UserExplorationReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=255)),
                ("prompt", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("generating", "Generating"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("context", models.JSONField(blank=True, default=dict)),
                ("revision_notes", models.TextField(blank=True)),
                ("narrative", models.TextField(blank=True)),
                ("sections", models.JSONField(blank=True, default=dict)),
                ("pdf_file", models.FileField(blank=True, upload_to="exploration_reports/")),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exploration_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddIndex(
            model_name="reportdocumentchunk",
            index=models.Index(fields=["report", "page_number"], name="reports_rep_report__a8f3c2_idx"),
        ),
        migrations.RunPython(backfill_report_defaults, migrations.RunPython.noop),
    ]
