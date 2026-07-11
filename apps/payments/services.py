import logging
import re
import uuid
from datetime import date, timedelta

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.models import AerialAnalysisGrant
from apps.compliance.models import LicenseAgreement
from apps.subscriptions.models import DownloadPurchase, UserSubscription

from .models import DocumentEmailLog, Invoice, PaymentOrder, Receipt
from .payment_pdf import build_payment_document_pdf
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

logger = logging.getLogger(__name__)


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


def _render_payment_pdf(
    *,
    kind: str,
    document_number: str,
    order: PaymentOrder,
    description: str,
) -> bytes:
    return build_payment_document_pdf(
        kind="receipt" if kind == "receipt" else "invoice",
        document_number=document_number,
        order=order,
        description=description,
        issued_date=timezone.now().strftime("%d %B %Y"),
    )


def ensure_invoice(order: PaymentOrder, *, regenerate: bool = False) -> Invoice:
    """Create (or optionally regenerate) the invoice PDF for an order."""
    existing = getattr(order, "invoice", None)
    if existing and not regenerate:
        if not existing.pdf_file:
            pdf = _render_payment_pdf(
                kind="invoice",
                document_number=existing.invoice_number,
                order=order,
                description=existing.description or order_description(order),
            )
            existing.pdf_file.save(f"{existing.invoice_number}.pdf", ContentFile(pdf), save=True)
        return existing

    description = order_description(order)
    if existing and regenerate:
        invoice_number = existing.invoice_number
        invoice = existing
        invoice.amount = order.amount
        invoice.currency = order.currency
        invoice.description = description
        invoice.save(update_fields=["amount", "currency", "description"])
    else:
        invoice_number = f"TM-INV-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        invoice = Invoice.objects.create(
            invoice_number=invoice_number,
            user=order.user,
            payment_order=order,
            amount=order.amount,
            currency=order.currency,
            description=description,
        )

    pdf = _render_payment_pdf(
        kind="invoice",
        document_number=invoice_number,
        order=order,
        description=description,
    )
    invoice.pdf_file.save(f"{invoice_number}.pdf", ContentFile(pdf), save=True)
    return invoice


def ensure_receipt(order: PaymentOrder, *, regenerate: bool = False) -> Receipt:
    """Create a payment receipt (completed orders only)."""
    if order.status != PaymentOrder.Status.COMPLETED:
        raise ValueError("Receipts can only be generated for completed orders.")

    existing = getattr(order, "receipt", None)
    if existing and not regenerate:
        if not existing.pdf_file:
            pdf = _render_payment_pdf(
                kind="receipt",
                document_number=existing.receipt_number,
                order=order,
                description=existing.description or order_description(order),
            )
            existing.pdf_file.save(f"{existing.receipt_number}.pdf", ContentFile(pdf), save=True)
        return existing

    description = order_description(order)
    if existing and regenerate:
        receipt_number = existing.receipt_number
        receipt = existing
        receipt.amount = order.amount
        receipt.currency = order.currency
        receipt.description = description
        receipt.save(update_fields=["amount", "currency", "description"])
    else:
        receipt_number = f"TM-RCP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        receipt = Receipt.objects.create(
            receipt_number=receipt_number,
            user=order.user,
            payment_order=order,
            amount=order.amount,
            currency=order.currency,
            description=description,
        )

    pdf = _render_payment_pdf(
        kind="receipt",
        document_number=receipt_number,
        order=order,
        description=description,
    )
    receipt.pdf_file.save(f"{receipt_number}.pdf", ContentFile(pdf), save=True)
    return receipt


@shared_task
def generate_invoice(payment_order_id):
    order = PaymentOrder.objects.select_related(
        "user", "subscription__plan", "report", "license_agreement"
    ).get(id=payment_order_id)
    return ensure_invoice(order).id


@shared_task
def generate_receipt(payment_order_id):
    order = PaymentOrder.objects.select_related(
        "user", "subscription__plan", "report", "license_agreement"
    ).get(id=payment_order_id)
    return ensure_receipt(order).id


def email_payment_document(
    order: PaymentOrder,
    document_type: str,
    *,
    to_email: str | None = None,
    sent_by: User | None = None,
    regenerate: bool = False,
) -> DocumentEmailLog:
    """Email invoice or receipt PDF to the customer (or an override address)."""
    recipient = (to_email or order.user.email or "").strip()
    if not recipient:
        raise ValueError("No email address available for this customer.")

    if document_type == DocumentEmailLog.DocumentType.INVOICE:
        document = ensure_invoice(order, regenerate=regenerate)
        document_number = document.invoice_number
        subject = f"Terra Meta invoice {document_number}"
        label = "invoice"
    elif document_type == DocumentEmailLog.DocumentType.RECEIPT:
        document = ensure_receipt(order, regenerate=regenerate)
        document_number = document.receipt_number
        subject = f"Terra Meta receipt {document_number}"
        label = "receipt"
    else:
        raise ValueError("document_type must be invoice or receipt.")

    if not document.pdf_file:
        raise ValueError(f"{label.capitalize()} PDF is missing.")

    description = document.description or order_description(order)
    text_body = (
        f"Hello,\n\n"
        f"Please find attached your Terra Meta {label} ({document_number}).\n\n"
        f"Order: {order.merchant_reference}\n"
        f"Amount: {order.amount} {order.currency}\n"
        f"Description: {description}\n\n"
        f"— Terra Meta billing\n"
    )
    html_body = (
        "<div style=\"font-family:Helvetica,Arial,sans-serif;color:#334155;line-height:1.5;\">"
        "<p style=\"color:#166534;font-weight:bold;margin:0 0 8px;\">Terra Meta</p>"
        f"<p>Hello,</p>"
        f"<p>Please find attached your Terra Meta <strong>{label}</strong> "
        f"(<code style=\"background:#f1f5f9;padding:2px 6px;border-radius:4px;\">{document_number}</code>).</p>"
        "<table style=\"border-collapse:collapse;width:100%;max-width:480px;margin:16px 0;"
        "border:1px solid #e2e8f0;\">"
        f"<tr><td style=\"padding:10px 12px;background:#f8fafc;color:#64748b;font-size:12px;\">Order</td>"
        f"<td style=\"padding:10px 12px;\"><code>{order.merchant_reference}</code></td></tr>"
        f"<tr><td style=\"padding:10px 12px;background:#f8fafc;color:#64748b;font-size:12px;\">Amount</td>"
        f"<td style=\"padding:10px 12px;font-weight:bold;color:#166534;\">{order.amount} {order.currency}</td></tr>"
        f"<tr><td style=\"padding:10px 12px;background:#f8fafc;color:#64748b;font-size:12px;\">Description</td>"
        f"<td style=\"padding:10px 12px;\">{description}</td></tr>"
        "</table>"
        "<p style=\"color:#64748b;font-size:13px;\">— Terra Meta · 5G Geology Futures</p>"
        "</div>"
    )

    log = DocumentEmailLog(
        payment_order=order,
        document_type=document_type,
        document_number=document_number,
        sent_to=recipient,
        sent_by=sent_by,
        status=DocumentEmailLog.Status.FAILED,
    )

    try:
        message = EmailMultiAlternatives(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            reply_to=[settings.EMAIL_HOST_USER or "admin@5ggeology.com"],
        )
        message.attach_alternative(html_body, "text/html")
        pdf_name = f"{document_number}.pdf"
        document.pdf_file.open("rb")
        try:
            message.attach(pdf_name, document.pdf_file.read(), "application/pdf")
        finally:
            document.pdf_file.close()
        message.send(fail_silently=False)

        now = timezone.now()
        document.email_sent_at = now
        document.email_sent_to = recipient
        document.email_send_count = (document.email_send_count or 0) + 1
        document.email_last_error = ""
        document.save(
            update_fields=["email_sent_at", "email_sent_to", "email_send_count", "email_last_error"]
        )
        log.status = DocumentEmailLog.Status.SENT
        log.save()
        logger.info("Sent %s %s to %s", label, document_number, recipient)
    except Exception as exc:
        log.error = str(exc)
        log.save()
        document.email_last_error = str(exc)
        document.save(update_fields=["email_last_error"])
        logger.exception("Failed sending %s %s to %s", label, document_number, recipient)
        raise

    return log


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

    # Sync generation so admin/dev work without a Celery worker.
    order = PaymentOrder.objects.select_related(
        "user", "subscription__plan", "report", "license_agreement"
    ).get(pk=order.pk)
    ensure_invoice(order)
    ensure_receipt(order)
    try:
        generate_invoice.delay(order.id)
    except Exception:
        logger.debug("Celery unavailable; invoice already generated synchronously", exc_info=True)


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
