from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0004_alter_report_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="geometry",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Optional GeoJSON Point or Polygon AOI for the report.",
            ),
        ),
        migrations.AddField(
            model_name="report",
            name="buffer_km",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Optional buffer (km) around geometry; max 20.",
                null=True,
            ),
        ),
    ]
