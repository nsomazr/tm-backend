from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="usersubscription",
            name="pesapal_account_reference",
        ),
    ]
