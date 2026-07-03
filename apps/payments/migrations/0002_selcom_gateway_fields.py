from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="paymentorder",
            old_name="pesapal_response",
            new_name="gateway_response",
        ),
        migrations.AddField(
            model_name="paymentorder",
            name="msisdn",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="paymentorder",
            name="payment_provider",
            field=models.CharField(
                choices=[
                    ("selcom", "Selcom"),
                    ("pesapal", "Pesapal"),
                    ("simulated", "Simulated"),
                ],
                default="simulated",
                max_length=20,
            ),
        ),
    ]
