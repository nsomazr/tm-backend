from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.accounts.email_templates import subscription_reminder_html, subscription_reminder_text
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
    user = subscription.user
    if not user.email:
        return

    name = user.first_name or user.username
    renew_url = f"{settings.FRONTEND_URL.rstrip('/')}/subscriptions"
    subject = f"Terra Meta: Subscription renews in {days_left} day(s)"
    text_body = subscription_reminder_text(
        name, subscription.plan.name, subscription.end_date, days_left, renew_url
    )
    html_body = subscription_reminder_html(
        name, subscription.plan.name, subscription.end_date, days_left, renew_url
    )

    message = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=True)
