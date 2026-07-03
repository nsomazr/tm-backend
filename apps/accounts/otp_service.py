import logging
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .email_templates import otp_email_html, otp_email_text
from .models import EmailOTP, User


OTP_TTL_MINUTES = 1
OTP_RESEND_SECONDS = 60
OTP_LENGTH = 6

logger = logging.getLogger(__name__)


def _generate_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(OTP_LENGTH))


def _generate_username(email: str) -> str:
    base = email.split("@")[0].lower()
    base = "".join(c for c in base if c.isalnum() or c in "._-")[:20] or "user"
    candidate = base
    suffix = 0
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}{suffix}"[:150]
    return candidate


def send_email_otp(email: str, purpose: str) -> None:
    email = email.strip().lower()
    latest = (
        EmailOTP.objects.filter(email=email, purpose=purpose)
        .order_by("-created_at")
        .first()
    )
    if latest and latest.created_at > timezone.now() - timedelta(seconds=OTP_RESEND_SECONDS):
        wait = OTP_RESEND_SECONDS - int((timezone.now() - latest.created_at).total_seconds())
        raise ValueError(f"Please wait {max(wait, 1)} seconds before requesting another code.")

    EmailOTP.objects.filter(email=email, purpose=purpose, used=False).update(used=True)

    code = _generate_code()
    expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
    EmailOTP.objects.create(email=email, code=code, purpose=purpose, expires_at=expires_at)

    subject = "Your Terra Meta sign-in code"
    if purpose == EmailOTP.Purpose.REGISTER:
        subject = "Your Terra Meta verification code"

    text_body = otp_email_text(code, purpose, OTP_TTL_MINUTES)
    html_body = otp_email_html(code, purpose, OTP_TTL_MINUTES)

    message = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        reply_to=[settings.EMAIL_HOST_USER or "admin@5ggeology.com"],
        headers={
            "X-Entity-Ref-ID": f"terra-meta-otp-{code[:2]}",
        },
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    if settings.DEBUG:
        logger.info("OTP sent to %s (purpose=%s): %s", email, purpose, code)


def verify_email_otp(email: str, code: str, purpose: str) -> tuple[User, bool]:
    email = email.strip().lower()
    code = code.strip()
    otp = (
        EmailOTP.objects.filter(
            email=email,
            code=code,
            purpose=purpose,
            used=False,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if not otp:
        raise ValueError("Invalid or expired code.")

    otp.used = True
    otp.save(update_fields=["used"])

    user = User.objects.filter(email__iexact=email).first()
    created = False
    if not user:
        if purpose == EmailOTP.Purpose.LOGIN:
            raise ValueError("No account found for this email.")
        user = User.objects.create(
            email=email,
            username=_generate_username(email),
            role=User.Role.FREE,
            profile_complete=False,
        )
        user.set_unusable_password()
        user.save()
        created = True

    return user, created


def get_or_create_password_user(email: str, password: str) -> tuple[User, bool]:
    email = email.strip().lower()
    user = User.objects.filter(email__iexact=email).first()
    if user:
        raise ValueError("An account with this email already exists. Sign in instead.")

    user = User.objects.create(
        email=email,
        username=_generate_username(email),
        role=User.Role.FREE,
        profile_complete=False,
    )
    user.set_password(password)
    user.save()
    return user, True
