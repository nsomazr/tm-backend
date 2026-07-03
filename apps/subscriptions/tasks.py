from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.accounts.models import User

from .models import UserSubscription


@shared_task
def check_subscription_expiry():
    today = timezone.now().date()
    expired = UserSubscription.objects.filter(
        status=UserSubscription.Status.ACTIVE,
        end_date__lt=today,
    )
    for sub in expired:
        sub.status = UserSubscription.Status.EXPIRED
        sub.save(update_fields=["status"])
        user = sub.user
        if user.role == User.Role.SUBSCRIBER:
            user.role = User.Role.FREE
            user.save(update_fields=["role"])


@shared_task
def send_renewal_reminders():
    today = timezone.now().date()
    for days in (7, 3, 1):
        target_date = today + timedelta(days=days)
        subs = UserSubscription.objects.filter(
            status=UserSubscription.Status.ACTIVE,
            end_date=target_date,
            auto_renew=True,
        ).select_related("user", "plan")
        for sub in subs:
            _send_reminder_email(sub, days)


def _send_reminder_email(subscription, days_left):
    subject = f"Terra Meta: Subscription renews in {days_left} day(s)"
    message = (
        f"Hello {subscription.user.first_name or subscription.user.username},\n\n"
        f"Your {subscription.plan.name} subscription expires on {subscription.end_date}. "
        f"Renew now to keep full access to mineral maps.\n\n"
        f"Visit {settings.FRONTEND_URL}/subscriptions to renew.\n\n"
        f"Terra Meta Team"
    )
    if subscription.user.email:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [subscription.user.email],
            fail_silently=True,
        )
