from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="country",
            name="bounds",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Bounding box: {"west", "south", "east", "north"}',
            ),
        ),
        migrations.AddField(
            model_name="country",
            name="boundary",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="GeoJSON geometry for country outline",
            ),
        ),
        migrations.AddField(
            model_name="country",
            name="center_lat",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="country",
            name="center_lng",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="country",
            name="default_zoom",
            field=models.PositiveSmallIntegerField(default=6),
        ),
    ]
