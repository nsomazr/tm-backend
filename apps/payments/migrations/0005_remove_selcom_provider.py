from django.db import migrations, models


def migrate_selcom_orders(apps, schema_editor):
    PaymentOrder = apps.get_model("payments", "PaymentOrder")
    PaymentOrder.objects.filter(payment_provider="selcom").update(payment_provider="snippe")


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_snippe_provider"),
    ]

    operations = [
        migrations.RunPython(migrate_selcom_orders, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="paymentorder",
            name="payment_provider",
            field=models.CharField(
                choices=[
                    ("snippe", "Snippe"),
                    ("simulated", "Simulated"),
                ],
                default="simulated",
                max_length=20,
            ),
        ),
    ]
