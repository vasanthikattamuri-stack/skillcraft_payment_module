"""
Thin wrapper around the official Razorpay Python SDK.

Why a wrapper?
  * One place that knows how to talk to Razorpay.
  * Razorpay/network errors are converted into our own safe exceptions, so
    raw gateway messages are never sent to the client.
  * Tests replace ``get_gateway()`` with a mock - no real API calls, no
    real credentials needed to run the test suite.
"""
import logging

import razorpay
import requests
from razorpay.errors import BadRequestError, ServerError
from razorpay.errors import GatewayError as RazorpaySDKGatewayError

from . import conf
from .exceptions import GatewayError, GatewayRequestRejected

logger = logging.getLogger("payments")

# Seconds to wait for Razorpay before giving up (passed through to `requests`).
REQUEST_TIMEOUT_SECONDS = 15


class RazorpayGateway:
    def __init__(self, client=None):
        # A client can be injected (useful for tests); otherwise it is created
        # lazily from settings the first time it is needed.
        self._client = client

    @property
    def client(self):
        if self._client is None:
            key_id, key_secret = conf.get_razorpay_credentials()
            self._client = razorpay.Client(auth=(key_id, key_secret))
            self._client.set_app_details({"title": "SkillCraft.AI Payments", "version": "1.0.0"})
        return self._client

    # ------------------------------------------------------------------ API

    def create_order(self, *, amount, currency, receipt, notes=None):
        """Create a Razorpay order. ``amount`` must already be in paise."""
        data = {
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "notes": notes or {},
        }
        return self._call("order.create", self.client.order.create, data=data)

    def fetch_payment(self, payment_id):
        """Fetch the latest state of a payment from Razorpay."""
        return self._call(
            "payment.fetch",
            self.client.payment.fetch,
            payment_id,
            reject_message="Payment could not be found at the payment gateway.",
        )

    def capture_payment(self, payment_id, amount, currency):
        """Capture an authorized payment (only used when auto-capture is off)."""
        return self._call(
            "payment.capture",
            self.client.payment.capture,
            payment_id,
            amount,
            data={"currency": currency},  # always pass a NEW dict (SDK mutates it)
        )

    # -------------------------------------------------------------- helpers

    def _call(self, operation, func, *args, reject_message=None, **kwargs):
        try:
            return func(*args, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
        except BadRequestError as exc:
            # Razorpay's message is logged for developers, not returned to users.
            logger.warning("Razorpay rejected %s: %s", operation, exc)
            raise GatewayRequestRejected(reject_message) from exc
        except (ServerError, RazorpaySDKGatewayError, requests.RequestException, ValueError) as exc:
            logger.error("Razorpay %s failed: %s", operation, exc.__class__.__name__)
            raise GatewayError() from exc


def get_gateway():
    """Factory used by services (patched in tests)."""
    return RazorpayGateway()
