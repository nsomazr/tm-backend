import logging
from typing import Any

from django.conf import settings
from selcom_apigw_client import apigwClient

logger = logging.getLogger(__name__)


class SelcomError(Exception):
    pass


class SelcomClient:
    """Selcom Checkout client (Push USSD Direct)."""

    def __init__(self) -> None:
        base_url = settings.SELCOM_BASE_URL.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        self._client = apigwClient.Client(
            baseUrl=base_url,
            apiKey=settings.SELCOM_API_KEY,
            apiSecret=settings.SELCOM_API_SECRET,
        )

    def _normalize_minimal(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {
            "amount": str(payload["amount"]).strip(),
            "currency": str(payload["currency"]).strip(),
            "buyer_name": str(payload.get("buyer_name", "")).strip(),
            "buyer_email": str(payload.get("buyer_email", "")).strip(),
            "buyer_phone": str(payload.get("buyer_phone", "")).strip(),
            "no_of_items": payload.get("no_of_items", 1),
        }
        if payload.get("order_id"):
            normalized["order_id"] = str(payload["order_id"]).strip()
        vendor = payload.get("vendor") or settings.SELCOM_VENDOR
        if vendor:
            normalized["vendor"] = str(vendor).strip()
        for key in ("buyer_remarks", "merchant_remarks"):
            if payload.get(key):
                normalized[key] = str(payload[key]).strip()
        normalized.pop("msisdn", None)
        return normalized

    def create_order_minimal(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/v1/checkout/create-order-minimal"
        return self._client.postFunc(path, self._normalize_minimal(payload))

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Hosted checkout page (cards, mobile money, and other Selcom methods)."""
        path = "/v1/checkout/create-order"
        normalized = self._normalize_full_order(payload)
        return self._client.postFunc(path, normalized)

    def _normalize_full_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {
            "amount": str(payload["amount"]).strip(),
            "currency": str(payload["currency"]).strip(),
            "buyer_name": str(payload.get("buyer_name", "")).strip(),
            "buyer_email": str(payload.get("buyer_email", "")).strip(),
            "buyer_phone": str(payload.get("buyer_phone", "")).strip(),
            "no_of_items": payload.get("no_of_items", 1),
            "payment_methods": str(payload.get("payment_methods", "ALL")).strip(),
        }
        if payload.get("order_id"):
            normalized["order_id"] = str(payload["order_id"]).strip()
        vendor = payload.get("vendor") or settings.SELCOM_VENDOR
        if vendor:
            normalized["vendor"] = str(vendor).strip()
        for key in ("redirect_url", "cancel_url", "webhook", "buyer_remarks", "merchant_remarks"):
            if payload.get(key):
                normalized[key] = str(payload[key]).strip()
        billing = payload.get("billing")
        if isinstance(billing, dict):
            for field, value in billing.items():
                if value:
                    normalized[f"billing.{field}"] = str(value).strip()
        return normalized

    def wallet_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = "/v1/checkout/wallet-payment"
        order_id = str(payload.get("order_id") or payload.get("transid") or "").strip()
        msisdn = str(payload.get("msisdn", "")).strip()
        if not order_id:
            raise SelcomError("order_id is required for wallet payment")
        if not msisdn:
            raise SelcomError("msisdn is required for wallet payment")
        normalized = {"transid": order_id, "order_id": order_id, "msisdn": msisdn}
        return self._client.postFunc(path, normalized)

    def order_status(self, order_id: str) -> dict[str, Any]:
        path = "/v1/checkout/order-status"
        params = {"order_id": order_id}
        if hasattr(self._client, "getFunc"):
            return self._client.getFunc(path, params)
        return self._client.postFunc(path, params)


def selcom_is_configured() -> bool:
    return bool(getattr(settings, "SELCOM_API_KEY", "") and getattr(settings, "SELCOM_VENDOR", ""))


def parse_selcom_paid(response: dict[str, Any]) -> bool:
    """Best-effort detection of a completed Selcom order."""
    if not response:
        return False
    status = str(
        response.get("status")
        or response.get("payment_status")
        or response.get("order_status")
        or ""
    ).upper()
    if status in {"PAID", "COMPLETED", "SUCCESS", "COMPLETE"}:
        return True
    result = str(response.get("result", "")).lower()
    if result == "success" and status in {"", "OK"}:
        return True
    data = response.get("data")
    if isinstance(data, dict):
        return parse_selcom_paid(data)
    return False


def extract_checkout_redirect(response: dict[str, Any]) -> str:
    """Extract hosted payment page URL from a Selcom create-order response."""
    if not isinstance(response, dict):
        return ""
    for key in ("payment_gateway_url", "redirect_url", "gateway_url", "url"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = response.get("data")
    if isinstance(data, dict):
        return extract_checkout_redirect(data)
    return ""
