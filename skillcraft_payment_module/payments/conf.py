"""
Central place where the payments app reads its configuration.

Every value is read from ``django.conf.settings`` *at call time* (not at
import time). This means:
  * the app has no dependency on the demo project's settings file, and
  * tests can change values with ``override_settings``.

Settings used by this app
-------------------------
RAZORPAY_KEY_ID                       (required) public key, e.g. rzp_test_xxx
RAZORPAY_KEY_SECRET                   (required) secret key - never exposed
RAZORPAY_WEBHOOK_SECRET               (required for webhooks)
PAYMENTS_COURSE_CATALOG_ADAPTER       dotted path to a course catalog adapter
PAYMENTS_ENROLLMENT_ADAPTER           dotted path to an enrollment adapter
PAYMENTS_COMBO_COURSE_IDS             list of course ids in the combo (demo adapter)
PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS  capture "authorized" payments on verify (default True)
PAYMENTS_ORDER_REUSE_MINUTES          reuse an unpaid identical order created within N minutes (default 30)
PAYMENTS_HISTORY_PAGE_SIZE            default page size for payment history (default 10)
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULT_COURSE_CATALOG_ADAPTER = "payments.adapters.demo.DemoCourseCatalogAdapter"
DEFAULT_ENROLLMENT_ADAPTER = "payments.adapters.demo.DemoEnrollmentAdapter"

# Razorpay currently supports INR for this LMS. Kept as a constant so it is
# never taken from the client.
CURRENCY = "INR"


def _get(name, default=None):
    return getattr(settings, name, default)


def get_razorpay_credentials():
    """Return (key_id, key_secret) or raise ImproperlyConfigured."""
    key_id = _get("RAZORPAY_KEY_ID", "")
    key_secret = _get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise ImproperlyConfigured(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set "
            "(use Razorpay Test Mode keys during development)."
        )
    return key_id, key_secret


def get_razorpay_key_id():
    """Public key id - safe to send to the frontend."""
    return get_razorpay_credentials()[0]


def get_razorpay_key_secret():
    """Secret key - used ONLY on the server for signature verification."""
    return get_razorpay_credentials()[1]


def get_webhook_secret():
    secret = _get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise ImproperlyConfigured("RAZORPAY_WEBHOOK_SECRET must be set.")
    return secret


def get_course_catalog_adapter_path():
    return _get("PAYMENTS_COURSE_CATALOG_ADAPTER", DEFAULT_COURSE_CATALOG_ADAPTER)


def get_enrollment_adapter_path():
    return _get("PAYMENTS_ENROLLMENT_ADAPTER", DEFAULT_ENROLLMENT_ADAPTER)


def get_combo_course_ids_setting():
    """Raw combo mapping from settings (used by the demo catalog adapter)."""
    return [str(cid) for cid in (_get("PAYMENTS_COMBO_COURSE_IDS", []) or [])]


def capture_authorized_payments():
    return bool(_get("PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS", True))


def order_reuse_minutes():
    return int(_get("PAYMENTS_ORDER_REUSE_MINUTES", 30))


def history_page_size():
    return int(_get("PAYMENTS_HISTORY_PAGE_SIZE", 10))
