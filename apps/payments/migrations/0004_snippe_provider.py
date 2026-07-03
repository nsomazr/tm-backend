from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_remove_pesapal_provider"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentorder",
            name="payment_provider",
            field=models.CharField(
                choices=[
                    ("snippe", "Snippe"),
                    ("selcom", "Selcom"),
                    ("simulated", "Simulated"),
                ],
                default="simulated",
                max_length=20,
            ),
        ),
    ]
