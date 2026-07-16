from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        ADMIN = "admin", "Platform Admin"
        MINERAL_MANAGER = "mineral_manager", "Mineral Manager"
        SUBSCRIBER = "subscriber", "Subscriber"
        FREE = "free", "Free User"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.FREE,
    )
    phone = models.CharField(max_length=20, blank=True)
    organization = models.CharField(max_length=255, blank=True)
    profile_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_admin_user(self):
        """Platform admins always have full product privileges."""
        if self.role in (self.Role.SUPER_ADMIN, self.Role.ADMIN):
            return True
        # Django createsuperuser / staff flags without a Terra role still count.
        return bool(getattr(self, "is_superuser", False))

    @property
    def is_mineral_manager(self):
        return self.role == self.Role.MINERAL_MANAGER

    @property
    def has_paid_access(self):
        if self.is_admin_user:
            return True
        today = timezone.now().date()
        from django.conf import settings

        from apps.payments.models import PaymentOrder

        qs = self.subscriptions.filter(
            status="active",
            end_date__gte=today,
            payment_orders__status=PaymentOrder.Status.COMPLETED,
        )
        if not getattr(settings, "PAYMENTS_SIMULATE", False):
            qs = qs.exclude(payment_orders__payment_provider="simulated")
        return qs.distinct().exists()

    def get_active_paid_subscription(self):
        """Return the current paid subscription, or None."""
        if self.is_admin_user:
            return None
        if not self.has_paid_access:
            return None
        from apps.reports.access import _active_paid_subscription

        return _active_paid_subscription(self)

    @property
    def can_use_analytics(self):
        """Analytics / hotspots: Plus and Pro only (not Starter / Explorer)."""
        if self.is_admin_user or self.role == self.Role.MINERAL_MANAGER:
            return True
        sub = self.get_active_paid_subscription()
        if not sub:
            return False
        # Plus/Pro include saved explorations; Starter does not.
        return bool(getattr(sub.plan, "includes_saved_explorations", False))

    @property
    def can_save_explorations(self):
        """Whether the user's plan allows saving drawn exploration areas."""
        if self.is_admin_user:
            return True
        today = timezone.now().date()
        from django.conf import settings

        from apps.payments.models import PaymentOrder

        qs = self.subscriptions.filter(
            status="active",
            end_date__gte=today,
            plan__includes_saved_explorations=True,
            payment_orders__status=PaymentOrder.Status.COMPLETED,
        )
        if not getattr(settings, "PAYMENTS_SIMULATE", False):
            qs = qs.exclude(payment_orders__payment_provider="simulated")
        return qs.distinct().exists()

    def __str__(self):
        return self.email or self.username


class EmailOTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Register"
        LOGIN = "login", "Login"

    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["email", "purpose", "used"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.purpose})"


class PhoneOTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Register"
        LOGIN = "login", "Login"

    phone = models.CharField(max_length=20, db_index=True)
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["phone", "purpose", "used"]),
        ]

    def __str__(self):
        return f"{self.phone} ({self.purpose})"
