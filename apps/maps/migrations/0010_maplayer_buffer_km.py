from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maps", "0009_deactivate_placeholder_layers"),
    ]

    operations = [
        migrations.AddField(
            model_name="maplayer",
            name="buffer_km",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text=(
                    "Optional reference buffer (km) around each feature. "
                    "Used when inferring map insights so nearby influencing factors are included."
                ),
                null=True,
                validators=[
                    MinValueValidator(5),
                    MaxValueValidator(20),
                ],
            ),
        ),
    ]
