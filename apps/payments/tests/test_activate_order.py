"""Tests for payment order activation."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.compliance.models import LicenseAgreement
from apps.payments.models import PaymentOrder
from apps.payments.services import activate_order
from apps.subscriptions.models import SubscriptionPlan, UserSubscription

User = get_user_model()


class ActivateOrderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer", password="pass")
        self.plan = SubscriptionPlan.objects.create(
            name="Plus",
            slug="monthly-standard-test",
            billing_cycle="monthly",
            price=Decimal("100000"),
            currency="TZS",
            includes_saved_explorations=True,
        )

    @patch("apps.payments.services.generate_invoice.delay")
    def test_subscription_cancels_prior_active_subs(self, _invoice_delay):
        old_sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status=UserSubscription.Status.ACTIVE,
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() + timedelta(days=20),
        )
        pending_sub = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            status=UserSubscription.Status.PENDING,
        )
        order = PaymentOrder.objects.create(
            user=self.user,
            order_type=PaymentOrder.OrderType.SUBSCRIPTION,
            amount=self.plan.price,
            currency="TZS",
            merchant_reference="sub-ref-1",
            subscription=pending_sub,
            status=PaymentOrder.Status.PENDING,
            payment_provider="simulated",
        )

        activate_order(order)

        old_sub.refresh_from_db()
        pending_sub.refresh_from_db()
        self.assertEqual(old_sub.status, UserSubscription.Status.CANCELLED)
        self.assertEqual(old_sub.end_date, date.today())
        self.assertEqual(pending_sub.status, UserSubscription.Status.ACTIVE)

    @patch("apps.payments.services.generate_invoice.delay")
    def test_license_payment_activates_agreement(self, _invoice_delay):
        license_agreement = LicenseAgreement.objects.create(
            company_name="Acme Mining",
            contact_name="Jane Doe",
            contact_email="jane@acme.test",
            terms="Standard license terms",
            price=Decimal("5000"),
            currency="USD",
            status=LicenseAgreement.Status.APPROVED,
        )
        order = PaymentOrder.objects.create(
            user=self.user,
            order_type=PaymentOrder.OrderType.LICENSE,
            amount=license_agreement.price,
            currency="USD",
            merchant_reference="lic-ref-1",
            license_agreement=license_agreement,
            status=PaymentOrder.Status.PENDING,
            payment_provider="simulated",
        )

        activate_order(order)

        license_agreement.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.COMPLETED)
        self.assertEqual(license_agreement.status, LicenseAgreement.Status.ACTIVE)
        self.assertEqual(license_agreement.start_date, date.today())
        self.assertIsNotNone(license_agreement.end_date)
