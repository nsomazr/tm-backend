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
        return self.role in (self.Role.SUPER_ADMIN, self.Role.ADMIN)

    @property
    def is_mineral_manager(self):
        return self.role == self.Role.MINERAL_MANAGER

    @property
    def has_paid_access(self):
        if self.role in (self.Role.SUPER_ADMIN, self.Role.ADMIN):
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
