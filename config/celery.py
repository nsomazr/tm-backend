import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("terra_meta")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "check-subscription-expiry": {
        "task": "apps.subscriptions.tasks.check_subscription_expiry",
        "schedule": crontab(hour=6, minute=0),
    },
    "send-renewal-reminders": {
        "task": "apps.subscriptions.tasks.send_renewal_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
}
