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
from apps.subscriptions.models import DownloadPurchase, UserSubscription

from .models import Invoice, PaymentOrder
from .selcom import SelcomClient, extract_checkout_redirect, parse_selcom_paid, selcom_is_configured


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


def _order_description(order):
    if order.order_type == PaymentOrder.OrderType.SUBSCRIPTION:
        return "Terra Meta subscription payment"
    if order.order_type == PaymentOrder.OrderType.DOWNLOAD:
        return f"Report download: {order.report.title if order.report else 'N/A'}"
    return "Terra Meta license payment"


def activate_order(order, transaction_data=None):
    order.status = PaymentOrder.Status.COMPLETED
    if transaction_data:
        order.gateway_response = {**order.gateway_response, "activation": transaction_data}
    order.save(update_fields=["status", "gateway_response", "updated_at"])

    if order.order_type == PaymentOrder.OrderType.SUBSCRIPTION and order.subscription:
        sub = order.subscription
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

    generate_invoice.delay(order.id)


def normalize_msisdn(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        return "255" + digits[1:]
    if not digits.startswith("255"):
        return "255" + digits
    return digits


def refresh_order_status(order: PaymentOrder) -> PaymentOrder:
    """Poll the payment gateway and activate the order when paid."""
    if order.status != PaymentOrder.Status.PENDING:
        return order

    if order.payment_provider == "selcom" and selcom_is_configured():
        tracking_id = order.order_tracking_id or order.merchant_reference
        client = SelcomClient()
        response = client.order_status(tracking_id)
        order.gateway_response = {**order.gateway_response, "order_status": response}
        if parse_selcom_paid(response):
            activate_order(order, response)
        else:
            order.save(update_fields=["gateway_response", "updated_at"])
    return order


def start_selcom_checkout(order: PaymentOrder, user: User, msisdn: str) -> PaymentOrder:
    client = SelcomClient()
    order_id = order.merchant_reference
    msisdn = normalize_msisdn(msisdn)
    create_payload = {
        "amount": str(int(order.amount)),
        "currency": order.currency,
        "order_id": order_id,
        "buyer_name": user.get_full_name() or user.username,
        "buyer_email": user.email or "",
        "buyer_phone": msisdn,
        "no_of_items": 1,
    }
    create_response = client.create_order_minimal(create_payload)
    order.payment_provider = "selcom"
    order.order_tracking_id = order_id
    order.msisdn = msisdn
    order.gateway_response = {"create_order": create_response}
    order.save()

    wallet_response = client.wallet_payment({"order_id": order_id, "msisdn": msisdn})
    order.gateway_response = {**order.gateway_response, "wallet_payment": wallet_response}
    order.save(update_fields=["gateway_response", "updated_at"])
    return order


def start_selcom_card_checkout(order: PaymentOrder, user: User) -> tuple[PaymentOrder, str]:
    client = SelcomClient()
    order_id = order.merchant_reference
    redirect_url = f"{settings.SELCOM_REDIRECT_URL.rstrip('/')}?ref={order_id}"
    create_payload = {
        "amount": str(int(order.amount)),
        "currency": order.currency,
        "order_id": order_id,
        "buyer_name": user.get_full_name() or user.username,
        "buyer_email": user.email or "",
        "buyer_phone": user.phone or "",
        "no_of_items": 1,
        "payment_methods": "ALL",
        "redirect_url": redirect_url,
        "cancel_url": settings.SELCOM_CANCEL_URL,
        "billing": {
            "firstname": user.first_name or user.username,
            "lastname": user.last_name or "",
            "country": "TZ",
            "email": user.email or "",
            "phone": user.phone or "",
        },
    }
    create_response = client.create_order(create_payload)
    gateway_url = extract_checkout_redirect(create_response)
    if not gateway_url:
        raise ValueError("Selcom did not return a payment page URL.")

    order.payment_provider = "selcom"
    order.order_tracking_id = order_id
    order.gateway_response = {"create_order": create_response}
    order.save(update_fields=["payment_provider", "order_tracking_id", "gateway_response", "updated_at"])
    return order, gateway_url
