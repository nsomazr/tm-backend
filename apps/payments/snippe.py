from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

SNIPPE_API_BASE = "https://api.snippe.sh"

ALLOWED_PAYMENT_URL_HOSTS = frozenset({
    "snippe.sh",
    "api.snippe.sh",
    "selcom.online",
    "tz.selcom.online",
})


class SnippeError(Exception):
    pass


class SnippeWebhookError(Exception):
    pass


def snippe_is_configured() -> bool:
    return bool(getattr(settings, "SNIPPE_API_KEY", ""))


def snippe_webhook_url() -> str:
    return f"{settings.BACKEND_URL.rstrip('/')}/api/v1/payments/webhooks/snippe/"


def snippe_idempotency_key(merchant_reference: str) -> str:
    return merchant_reference[:30]


class SnippeClient:
    def __init__(self) -> None:
        self.api_key = settings.SNIPPE_API_KEY
        self.base_url = getattr(settings, "SNIPPE_BASE_URL", SNIPPE_API_BASE).rstrip("/")

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def create_payment(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/v1/payments",
            headers=self._headers(idempotency_key),
            json=payload,
            timeout=45,
        )
        body = _parse_json(response)
        if response.status_code >= 400 or body.get("status") == "error":
            message = body.get("message") or body.get("error_code") or response.text
            raise SnippeError(str(message))
        return body

    def get_payment(self, reference: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/v1/payments/{reference}",
            headers=self._headers(),
            timeout=30,
        )
        body = _parse_json(response)
        if response.status_code >= 400 or body.get("status") == "error":
            message = body.get("message") or body.get("error_code") or response.text
            raise SnippeError(str(message))
        return body


def _parse_json(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"status": "error", "message": response.text}


def extract_payment_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def extract_payment_url(response: dict[str, Any]) -> str:
    payment_url = extract_payment_data(response).get("payment_url") or ""
    if not payment_url:
        return ""
    host = urlparse(payment_url).hostname or ""
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_PAYMENT_URL_HOSTS):
        raise SnippeError("Snippe returned an unexpected payment URL.")
    return payment_url


def parse_snippe_paid(response: dict[str, Any]) -> bool:
    data = extract_payment_data(response) if "data" in response else response
    status = str(data.get("status", "")).lower()
    return status in {"completed", "success", "paid"}


def verify_snippe_webhook(raw_body: str, headers: dict[str, str]) -> dict[str, Any]:
    signing_key = getattr(settings, "SNIPPE_WEBHOOK_SECRET", "")
    if snippe_is_configured():
        if not signing_key:
            raise SnippeWebhookError("Webhook secret not configured.")
        timestamp = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp") or ""
        signature = headers.get("X-Webhook-Signature") or headers.get("x-webhook-signature") or ""
        if not timestamp or not signature:
            raise SnippeWebhookError("Missing webhook signature headers.")
        event_time = int(timestamp)
        if abs(int(time.time()) - event_time) > 300:
            raise SnippeWebhookError("Webhook timestamp too old.")
        message = f"{timestamp}.{raw_body}"
        expected = hmac.new(
            signing_key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise SnippeWebhookError("Invalid webhook signature.")
    elif signing_key:
        timestamp = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp") or ""
        signature = headers.get("X-Webhook-Signature") or headers.get("x-webhook-signature") or ""
        if timestamp and signature:
            event_time = int(timestamp)
            if abs(int(time.time()) - event_time) > 300:
                raise SnippeWebhookError("Webhook timestamp too old.")
            message = f"{timestamp}.{raw_body}"
            expected = hmac.new(
                signing_key.encode(),
                message.encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise SnippeWebhookError("Invalid webhook signature.")

    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise SnippeWebhookError("Invalid webhook JSON.") from exc


def webhook_event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or "")


def webhook_event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, dict):
        return data
    return event


def webhook_order_reference(data: dict[str, Any]) -> str:
    metadata = data.get("metadata") or {}
    if isinstance(metadata, dict):
        order_id = metadata.get("order_id")
        if order_id:
            return str(order_id)
    return ""
