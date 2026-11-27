"""
Razorpay signature verification (HMAC-SHA256).

There are TWO different signatures and they must not be mixed up:

1. CHECKOUT signature  (returned to the browser after payment)
       message = "<razorpay_order_id>|<razorpay_payment_id>"
       key     = RAZORPAY_KEY_SECRET
   Proves the order_id/payment_id pair really came from Razorpay Checkout.
   It does NOT prove the money was captured - we still check the payment
   status with Razorpay before granting access.

2. WEBHOOK signature   (header ``X-Razorpay-Signature`` on webhook calls)
       message = the RAW request body bytes, exactly as received
       key     = RAZORPAY_WEBHOOK_SECRET (set in the Razorpay Dashboard)
   Proves the webhook was sent by Razorpay and was not modified.

``hmac.compare_digest`` is used for comparison because it takes the same time
whether the strings match or not (prevents timing attacks).
"""
import hashlib
import hmac


def _hmac_sha256_hex(secret, message_bytes):
    return hmac.new(secret.encode("utf-8"), message_bytes, hashlib.sha256).hexdigest()


def generate_checkout_signature(razorpay_order_id, razorpay_payment_id, key_secret):
    """Compute the checkout signature (used by verification and by tests)."""
    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    return _hmac_sha256_hex(key_secret, message)


def verify_checkout_signature(razorpay_order_id, razorpay_payment_id, signature, key_secret):
    """Return True only if the checkout signature is valid."""
    if not (razorpay_order_id and razorpay_payment_id and signature and key_secret):
        return False
    expected = generate_checkout_signature(razorpay_order_id, razorpay_payment_id, key_secret)
    return hmac.compare_digest(expected, str(signature))


def generate_webhook_signature(raw_body, webhook_secret):
    """Compute the webhook signature for a raw body (bytes)."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    return _hmac_sha256_hex(webhook_secret, raw_body)


def verify_webhook_signature(raw_body, signature, webhook_secret):
    """
    Return True only if ``signature`` matches the RAW body.

    IMPORTANT: pass ``request.body`` (bytes). Never re-serialise parsed JSON,
    because even a whitespace change produces a different signature.
    """
    if not (raw_body and signature and webhook_secret):
        return False
    expected = generate_webhook_signature(raw_body, webhook_secret)
    return hmac.compare_digest(expected, str(signature))
