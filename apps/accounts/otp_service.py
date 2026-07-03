import logging
import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .email_templates import otp_email_html, otp_email_text
from .models import EmailOTP, User


OTP_TTL_MINUTES = 1
OTP_RESEND_SECONDS = 60
OTP_LENGTH = 6
OTP_SEND_HOUR_LIMIT = 10
OTP_VERIFY_MAX_ATTEMPTS = 5
OTP_VERIFY_LOCKOUT_SECONDS = 900

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


def _send_hour_cache_key(email: str) -> str:
    return f"otp_send_hour:{email}"


def _verify_fail_cache_key(email: str, purpose: str) -> str:
    return f"otp_verify_fail:{email}:{purpose}"


def _check_verify_lockout(email: str, purpose: str) -> None:
    failures = cache.get(_verify_fail_cache_key(email, purpose), 0)
    if failures >= OTP_VERIFY_MAX_ATTEMPTS:
        raise ValueError("Too many failed attempts. Request a new code and try again later.")


def _record_verify_failure(email: str, purpose: str) -> None:
    key = _verify_fail_cache_key(email, purpose)
    failures = cache.get(key, 0) + 1
    cache.set(key, failures, OTP_VERIFY_LOCKOUT_SECONDS)


def _clear_verify_failures(email: str, purpose: str) -> None:
    cache.delete(_verify_fail_cache_key(email, purpose))


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

    hour_key = _send_hour_cache_key(email)
    send_count = cache.get(hour_key, 0)
    if send_count >= OTP_SEND_HOUR_LIMIT:
        raise ValueError("Too many verification codes requested. Try again later.")

    EmailOTP.objects.filter(email=email, purpose=purpose, used=False).update(used=True)

    code = _generate_code()
    expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
    EmailOTP.objects.create(email=email, code=code, purpose=purpose, expires_at=expires_at)
    cache.set(hour_key, send_count + 1, 3600)

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
            "X-Entity-Ref-ID": f"terra-meta-otp-{secrets.token_hex(4)}",
        },
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    logger.info("OTP email dispatched to %s (purpose=%s)", email, purpose)


def verify_email_otp(email: str, code: str, purpose: str) -> tuple[User, bool]:
    email = email.strip().lower()
    code = code.strip()
    _check_verify_lockout(email, purpose)

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
        _record_verify_failure(email, purpose)
        raise ValueError("Invalid or expired code.")

    otp.used = True
    otp.save(update_fields=["used"])
    _clear_verify_failures(email, purpose)

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
