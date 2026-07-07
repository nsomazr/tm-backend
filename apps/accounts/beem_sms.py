"""Send SMS via Beem Africa (https://beem.africa)."""

from __future__ import annotations

import base64
import json
import logging

import requests
from django.conf import settings

from .phone_utils import beem_dest_addr

logger = logging.getLogger(__name__)

BEEM_SEND_URL = "https://apisms.beem.africa/v1/send"


class BeemSmsError(Exception):
    pass


def beem_sms_configured() -> bool:
    return bool(getattr(settings, "BEEM_SMS_API_KEY", "") and getattr(settings, "BEEM_SMS_SECRET_KEY", ""))


def send_sms(phone: str, message: str) -> bool:
    api_key = getattr(settings, "BEEM_SMS_API_KEY", "")
    secret_key = getattr(settings, "BEEM_SMS_SECRET_KEY", "")
    source_addr = getattr(settings, "BEEM_SMS_SOURCE_ADDR", "NILEAGI")

    if not api_key or not secret_key:
        if settings.DEBUG:
            logger.warning("BEEM SMS not configured; message to %s: %s", phone, message)
            return True
        raise BeemSmsError("SMS verification is not available right now.")

    dest = beem_dest_addr(phone)
    auth = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    payload = {
        "source_addr": source_addr,
        "encoding": 0,
        "schedule_time": "",
        "message": message,
        "recipients": [{"recipient_id": "1", "dest_addr": dest}],
    }
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            BEEM_SEND_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=30,
            verify=getattr(settings, "BEEM_SMS_VERIFY_SSL", True),
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.exception("Beem SMS request failed for %s", dest)
        raise BeemSmsError("Could not send SMS. Please try again later.") from exc

    if not data.get("successful", False):
        logger.error("Beem SMS rejected for %s: %s", dest, data)
        raise BeemSmsError("SMS could not be delivered. Check the number and try again.")

    logger.info("Beem SMS sent to %s", dest)
    return True
