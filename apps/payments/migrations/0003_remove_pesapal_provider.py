from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_selcom_gateway_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentorder",
            name="payment_provider",
            field=models.CharField(
                choices=[("selcom", "Selcom"), ("simulated", "Simulated")],
                default="simulated",
                max_length=20,
            ),
        ),
    ]
