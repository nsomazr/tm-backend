import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("maps", "0005_savedexploration"),
    ]

    operations = [
        migrations.AddField(
            model_name="mapfeature",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_features",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
