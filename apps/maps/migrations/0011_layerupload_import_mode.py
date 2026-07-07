from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maps", "0010_maplayer_buffer_km"),
    ]

    operations = [
        migrations.AddField(
            model_name="layerupload",
            name="import_mode",
            field=models.CharField(
                choices=[("replace", "Replace existing"), ("append", "Add to existing")],
                default="replace",
                max_length=20,
            ),
        ),
    ]
