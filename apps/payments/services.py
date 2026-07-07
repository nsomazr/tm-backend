import re
import uuid
from datetime import date, timedelta
from io import BytesIO

from celery import shared_task
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from django.conf import settings

from apps.accounts.models import User
from apps.analytics.models import AerialAnalysisGrant
from apps.compliance.models import LicenseAgreement
from apps.subscriptions.models import DownloadPurchase, UserSubscription

from .models import Invoice, PaymentOrder
from .snippe import (
    SnippeClient,
    SnippeError,
    extract_payment_data,
    extract_payment_url,
    parse_snippe_paid,
    snippe_idempotency_key,
    snippe_is_configured,
    snippe_webhook_url,
)


@shared_task
def generate_invoice(payment_order_id):
    order = PaymentOrder.objects.select_related("user").get(id=payment_order_id)
    if hasattr(order, "invoice"):
        return order.invoice.id

    invoice_number = f"TM-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    description = _order_description(order)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(72, 750, "Terra Meta Invoice")
    p.setFont("Helvetica", 12)
    p.drawString(72, 720, f"Invoice #: {invoice_number}")
    p.drawString(72, 700, f"Date: {timezone.now().strftime('%Y-%m-%d')}")
    p.drawString(72, 680, f"Customer: {order.user.get_full_name() or order.user.username}")
    p.drawString(72, 660, f"Email: {order.user.email}")
    p.drawString(72, 630, f"Description: {description}")
    p.drawString(72, 610, f"Amount: {order.amount} {order.currency}")
    p.drawString(72, 590, f"Status: {order.status}")
    p.showPage()
    p.save()

    from django.core.files.base import ContentFile

    invoice = Invoice.objects.create(
        invoice_number=invoice_number,
        user=order.user,
        payment_order=order,
        amount=order.amount,
        currency=order.currency,
        description=description,
    )
    invoice.pdf_file.save(
        f"{invoice_number}.pdf",
        ContentFile(buffer.getvalue()),
        save=True,
    )
    return invoice.id


def order_description(order):
    """Human-readable line for invoices and admin order detail."""
    if order.order_type == PaymentOrder.OrderType.SUBSCRIPTION:
        if order.subscription_id:
            plan = order.subscription.plan
            cycle = plan.get_billing_cycle_display()
            return f"{plan.name} subscription ({cycle.lower()})"
        return "Terra Meta subscription payment"
    if order.order_type == PaymentOrder.OrderType.DOWNLOAD:
        return f"Report download: {order.report.title if order.report else 'N/A'}"
    if order.order_type == PaymentOrder.OrderType.AERIAL:
        aerial = (order.gateway_response or {}).get("aerial", {})
        extra = aerial.get("purchased_extra_km2", 0)
        return f"Extended aerial map analysis (+{extra:.0f} km²)"
    if order.order_type == PaymentOrder.OrderType.LICENSE:
        if order.license_agreement_id:
            return f"License agreement: {order.license_agreement.company_name}"
        return "Terra Meta license payment"
    return "Terra Meta payment"


def _order_description(order):
    return order_description(order)


def _cancel_other_subscriptions(user, active_sub):
    """End prior active/pending subscriptions when a new plan is activated."""
    today = date.today()
    UserSubscription.objects.filter(
        user=user,
        status=UserSubscription.Status.ACTIVE,
    ).exclude(pk=active_sub.pk).update(
        status=UserSubscription.Status.CANCELLED,
        end_date=today,
    )
    UserSubscription.objects.filter(
        user=user,
        status=UserSubscription.Status.PENDING,
    ).exclude(pk=active_sub.pk).update(status=UserSubscription.Status.CANCELLED)


def activate_order(order, transaction_data=None):
    order.status = PaymentOrder.Status.COMPLETED
    if transaction_data:
        order.gateway_response = {**order.gateway_response, "activation": transaction_data}
    order.save(update_fields=["status", "gateway_response", "updated_at"])

    if order.order_type == PaymentOrder.OrderType.SUBSCRIPTION and order.subscription:
        sub = order.subscription
        _cancel_other_subscriptions(order.user, sub)
        sub.status = UserSubscription.Status.ACTIVE
        sub.start_date = date.today()
        cycle_days = 365 if sub.plan.billing_cycle == "annual" else 30
        sub.end_date = date.today() + timedelta(days=cycle_days)
        sub.save(update_fields=["status", "start_date", "end_date"])
        user = order.user
        if user.role not in (
            User.Role.SUPER_ADMIN,
            User.Role.ADMIN,
            User.Role.MINERAL_MANAGER,
        ):
            user.role = User.Role.SUBSCRIBER
            user.save(update_fields=["role"])

    elif order.order_type == PaymentOrder.OrderType.DOWNLOAD and order.report:
        DownloadPurchase.objects.get_or_create(
            user=order.user,
            report=order.report,
            defaults={
                "amount_paid": order.amount,
                "currency": order.currency,
            },
        )

    elif order.order_type == PaymentOrder.OrderType.AERIAL:
        aerial = (order.gateway_response or {}).get("aerial", {})
        if aerial:
            AerialAnalysisGrant.objects.create(
                user=order.user,
                payment_order=order,
                lat=float(aerial["lat"]),
                lng=float(aerial["lng"]),
                zoom=int(aerial.get("zoom", 8)),
                max_area_km2=float(aerial["max_area_km2"]),
                purchased_extra_km2=float(aerial.get("purchased_extra_km2", 0)),
            )

    elif order.order_type == PaymentOrder.OrderType.LICENSE and order.license_agreement:
        license_agreement = order.license_agreement
        license_agreement.status = LicenseAgreement.Status.ACTIVE
        license_agreement.start_date = date.today()
        if not license_agreement.end_date or license_agreement.end_date < date.today():
            license_agreement.end_date = date.today() + timedelta(days=365)
        license_agreement.save(update_fields=["status", "start_date", "end_date"])

    generate_invoice.delay(order.id)


def fail_order(order, transaction_data=None):
    if order.status == PaymentOrder.Status.COMPLETED:
        return order
    order.status = PaymentOrder.Status.FAILED
    if transaction_data:
        order.gateway_response = {**order.gateway_response, "failure": transaction_data}
    order.save(update_fields=["status", "gateway_response", "updated_at"])
    return order


def normalize_msisdn(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        return "255" + digits[1:]
    if not digits.startswith("255"):
        return "255" + digits
    return digits


def _customer_fields(user: User, *, name: str | None = None, email: str | None = None) -> dict[str, str]:
    full_name = (name or user.get_full_name() or user.username).strip()
    name_parts = full_name.split(None, 1)
    first_name = name_parts[0] if name_parts else user.username
    last_name = name_parts[1] if len(name_parts) > 1 else "Customer"
    return {
        "firstname": first_name,
        "lastname": last_name,
        "email": (email or user.email or f"{user.username}@terra-meta.local").strip(),
    }


def _snippe_amount(order: PaymentOrder) -> int:
    return int(order.amount)


def refresh_order_status(order: PaymentOrder) -> PaymentOrder:
    """Poll the payment gateway and activate the order when paid."""
    if order.status != PaymentOrder.Status.PENDING:
        return order

    if order.payment_provider == "snippe" and snippe_is_configured() and order.order_tracking_id:
        client = SnippeClient()
        try:
            response = client.get_payment(order.order_tracking_id)
        except SnippeError as exc:
            order.gateway_response = {**order.gateway_response, "order_status_error": str(exc)}
            order.save(update_fields=["gateway_response", "updated_at"])
            return order
        order.gateway_response = {**order.gateway_response, "order_status": response}
        if parse_snippe_paid(response):
            activate_order(order, extract_payment_data(response))
        else:
            order.save(update_fields=["gateway_response", "updated_at"])
        return order

    return order


def start_snippe_mobile_checkout(order: PaymentOrder, user: User, msisdn: str) -> PaymentOrder:
    client = SnippeClient()
    msisdn = normalize_msisdn(msisdn)
    customer = _customer_fields(user)
    payload = {
        "payment_type": "mobile",
        "details": {
            "amount": _snippe_amount(order),
            "currency": order.currency,
        },
        "phone_number": msisdn,
        "customer": customer,
        "webhook_url": snippe_webhook_url(),
        "metadata": {"order_id": order.merchant_reference},
    }
    create_response = client.create_payment(
        payload,
        idempotency_key=snippe_idempotency_key(order.merchant_reference),
    )
    payment_data = extract_payment_data(create_response)
    order.payment_provider = "snippe"
    order.order_tracking_id = payment_data.get("reference", "")
    order.msisdn = msisdn
    order.gateway_response = {"create_payment": create_response}
    order.save()
    return order


def start_snippe_card_checkout(
    order: PaymentOrder,
    user: User,
    *,
    cardholder_name: str | None = None,
    billing_email: str | None = None,
    msisdn: str | None = None,
) -> tuple[PaymentOrder, str]:
    client = SnippeClient()
    customer = _customer_fields(user, name=cardholder_name, email=billing_email)
    redirect_url = f"{settings.SNIPPE_REDIRECT_URL.rstrip('/')}?ref={order.merchant_reference}"
    phone_number = normalize_msisdn(msisdn or user.phone or "255700000000")
    payload = {
        "payment_type": "card",
        "details": {
            "amount": _snippe_amount(order),
            "currency": order.currency,
            "redirect_url": redirect_url,
            "cancel_url": settings.SNIPPE_CANCEL_URL,
        },
        "phone_number": phone_number,
        "customer": {
            **customer,
            "address": "Dar es Salaam",
            "city": "Dar es Salaam",
            "state": "DSM",
            "postcode": "14101",
            "country": "TZ",
        },
        "webhook_url": snippe_webhook_url(),
        "metadata": {"order_id": order.merchant_reference},
    }
    create_response = client.create_payment(
        payload,
        idempotency_key=snippe_idempotency_key(order.merchant_reference),
    )
    gateway_url = extract_payment_url(create_response)
    if not gateway_url:
        raise SnippeError("Snippe did not return a payment page URL.")

    payment_data = extract_payment_data(create_response)
    order.payment_provider = "snippe"
    order.order_tracking_id = payment_data.get("reference", "")
    order.gateway_response = {"create_payment": create_response}
    order.save(update_fields=["payment_provider", "order_tracking_id", "gateway_response", "updated_at"])
    return order, gateway_url
