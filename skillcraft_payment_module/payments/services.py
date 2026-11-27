"""
Business logic for the payments module.

Views stay thin: they validate input with serializers and call the functions
in this file. All money/state decisions happen here.

Main functions
--------------
create_payment_order(user, purchase_type, course_id)       -> API 1
verify_checkout_payment(user, order_id, payment_id, sig)   -> API 2
process_webhook(raw_body, signature, event_id)             -> API 3
get_order_for_user(user, razorpay_order_id)                -> API 4
activate_enrollment_after_payment(order)                   -> LMS hook

Golden rules enforced here
--------------------------
1. Prices come from ``pricing.py`` - never from the request.
2. A valid checkout signature is NOT proof of payment. Access is granted only
   when Razorpay reports the payment as ``captured``.
3. Every payment is checked against its order: order id, amount, currency.
4. State changes run inside ``transaction.atomic()`` with the order row
   locked (``select_for_update``), so the Verify API and a webhook arriving
   at the same moment cannot double-process a payment.
5. Payment status only moves forward (see ``Payment.STATUS_RANK``).
6. Enrollment is activated at most once per order (``enrollment_activated``).
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import conf
from .adapters import get_course_catalog, get_enrollment_adapter
from .exceptions import (
    AlreadyPurchasedError,
    ComboNotConfiguredError,
    GatewayError,
    InvalidPurchaseError,
    OrderNotFoundError,
    PaymentError,
    PaymentMismatchError,
    SignatureVerificationFailed,
)
from .gateway import get_gateway
from .models import Payment, PaymentOrder, PurchaseType, WebhookEvent, generate_internal_order_id
from .pricing import get_price_paise
from .signatures import verify_checkout_signature, verify_webhook_signature

logger = logging.getLogger("payments")

COMBO_TITLE = "Complete Combo Package"

# Razorpay payment "status" string -> our Payment.Status
RAZORPAY_STATUS_MAP = {
    "created": Payment.Status.CREATED,
    "authorized": Payment.Status.AUTHORIZED,
    "captured": Payment.Status.CAPTURED,
    "failed": Payment.Status.FAILED,
    "refunded": Payment.Status.REFUNDED,
}

HANDLED_WEBHOOK_EVENTS = {"payment.captured", "payment.failed", "order.paid"}


@dataclass
class PaymentOutcome:
    """Result of applying a Razorpay payment to an order."""

    order: PaymentOrder
    payment: Payment
    # One of: "captured", "authorized", "failed", "refunded", "created"
    outcome: str


@dataclass
class WebhookResult:
    http_status: int
    success: bool
    message: str
    event_status: str


# =========================================================================
# API 1 - Create order
# =========================================================================

def _resolve_purchase(purchase_type, course_id):
    """
    Validate what is being bought and return
    (stored_course_id, title, included_course_ids).
    """
    catalog = get_course_catalog()

    if purchase_type == PurchaseType.COURSE:
        course_id = str(course_id or "").strip()
        course = catalog.get_course(course_id) if course_id else None
        if course is None:
            raise InvalidPurchaseError(
                "Invalid course_id: the course does not exist or cannot be purchased.",
                errors={"course_id": ["Invalid or unavailable course."]},
            )
        return course.course_id, course.title, [course.course_id]

    if purchase_type == PurchaseType.COMBO:
        # Remove duplicates while keeping order.
        combo_ids = list(dict.fromkeys(str(cid) for cid in catalog.get_combo_course_ids()))
        if not combo_ids:
            logger.error("Combo purchase attempted but no combo course mapping is configured.")
            raise ComboNotConfiguredError()
        return "", COMBO_TITLE, combo_ids

    raise InvalidPurchaseError(
        "Invalid purchase_type. Allowed values: course, combo.",
        errors={"purchase_type": ["Invalid purchase type."]},
    )


def _user_already_owns(user, purchase_type, course_id, included_course_ids):
    """True if the user already paid for (or otherwise has) this purchase."""
    paid = PaymentOrder.objects.filter(user=user, status=PaymentOrder.Status.PAID)

    if purchase_type == PurchaseType.COMBO:
        if paid.filter(purchase_type=PurchaseType.COMBO).exists():
            return True
    else:
        if paid.filter(purchase_type=PurchaseType.COURSE, course_id=course_id).exists():
            return True
        # A course already included in a paid combo cannot be bought again.
        # (Checked in Python so it works on SQLite and PostgreSQL alike.)
        for combo in paid.filter(purchase_type=PurchaseType.COMBO).only("included_course_ids"):
            if course_id in combo.get_course_ids():
                return True

    return bool(get_enrollment_adapter().user_has_access(user=user, course_ids=included_course_ids))


def create_payment_order(*, user, purchase_type, course_id=None):
    """
    Create (or reuse) a Razorpay order for ``user``.

    Returns ``(order, reused)``; ``reused`` is True when a recent identical
    unpaid order was returned instead of creating a new one (protects against
    double clicks creating many orders).
    """
    stored_course_id, title, included_ids = _resolve_purchase(purchase_type, course_id)

    # Price is decided HERE, by the backend. Anything the client sent is ignored.
    amount = get_price_paise(purchase_type)
    currency = conf.CURRENCY

    if _user_already_owns(user, purchase_type, stored_course_id, included_ids):
        raise AlreadyPurchasedError()

    reuse_minutes = conf.order_reuse_minutes()
    if reuse_minutes > 0:
        existing = (
            PaymentOrder.objects.filter(
                user=user,
                purchase_type=purchase_type,
                course_id=stored_course_id,
                status=PaymentOrder.Status.CREATED,
                amount=amount,
                currency=currency,
                created_at__gte=timezone.now() - timedelta(minutes=reuse_minutes),
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            logger.info("Reusing unpaid order %s for user_id=%s", existing.internal_order_id, user.pk)
            return existing, True

    internal_order_id = generate_internal_order_id()
    razorpay_order = get_gateway().create_order(
        amount=amount,
        currency=currency,
        receipt=internal_order_id,
        notes={
            # Notes are visible in the Razorpay Dashboard - no personal data.
            "internal_order_id": internal_order_id,
            "purchase_type": purchase_type,
            "course_id": stored_course_id or "combo",
            "user_id": str(user.pk),
        },
    )

    # Never trust the gateway response blindly either.
    razorpay_order_id = (razorpay_order or {}).get("id")
    if (
        not razorpay_order_id
        or int(razorpay_order.get("amount", -1)) != amount
        or str(razorpay_order.get("currency", "")).upper() != currency
    ):
        logger.error("Unexpected Razorpay order response for receipt %s", internal_order_id)
        raise GatewayError()

    order = PaymentOrder.objects.create(
        internal_order_id=internal_order_id,
        razorpay_order_id=razorpay_order_id,
        user=user,
        purchase_type=purchase_type,
        course_id=stored_course_id,
        course_title=title,
        included_course_ids=included_ids,
        amount=amount,
        currency=currency,
        status=PaymentOrder.Status.CREATED,
    )
    logger.info(
        "Created order %s (%s) type=%s amount=%s %s user_id=%s",
        order.internal_order_id, razorpay_order_id, purchase_type, amount, currency, user.pk,
    )
    return order, False


# =========================================================================
# Shared core: apply a Razorpay payment entity to an order
# =========================================================================

def _validate_payment_matches_order(order, entity):
    """Raise PaymentMismatchError unless the payment belongs to this order."""
    problems = []
    if entity.get("order_id") != order.razorpay_order_id:
        problems.append("order_id")
    try:
        if int(entity.get("amount", -1)) != order.amount:
            problems.append("amount")
    except (TypeError, ValueError):
        problems.append("amount")
    if str(entity.get("currency", "")).upper() != order.currency:
        problems.append("currency")
    if problems:
        logger.error(
            "Payment %s does not match order %s (mismatched: %s)",
            entity.get("id"), order.internal_order_id, ", ".join(problems),
        )
        raise PaymentMismatchError(errors={"mismatch": problems})


def apply_payment_entity(order, entity, *, source):
    """
    Record the state of a Razorpay payment against ``order``.

    MUST be called inside ``transaction.atomic()`` with ``order`` fetched via
    ``select_for_update()``. Used by BOTH the Verify API and the webhook, so
    the two paths always behave identically and are safe to run in any order
    and any number of times (idempotent).
    """
    _validate_payment_matches_order(order, entity)

    payment_id = entity.get("id")
    if not payment_id:
        raise PaymentMismatchError("Payment id missing from gateway data.")

    new_status = RAZORPAY_STATUS_MAP.get(str(entity.get("status", "")).lower())
    if new_status is None:
        raise PaymentMismatchError("Unknown payment status received from gateway.")

    now = timezone.now()
    payment, created = Payment.objects.select_for_update().get_or_create(
        razorpay_payment_id=payment_id,
        defaults={
            "order": order,
            "amount": order.amount,
            "currency": order.currency,
            "status": new_status,
        },
    )
    if payment.order_id != order.pk:
        logger.error("Payment %s is already linked to another order.", payment_id)
        raise PaymentMismatchError()

    # Only move the payment status forward (protects against out-of-order events).
    if not created and Payment.STATUS_RANK[new_status] > Payment.STATUS_RANK[payment.status]:
        payment.status = new_status

    payment.method = str(entity.get("method") or payment.method or "")[:32]
    payment.source = source[:40]
    if payment.status == Payment.Status.FAILED:
        # Razorpay error codes/descriptions are safe, generic messages.
        payment.error_code = str(entity.get("error_code") or "")[:64]
        payment.error_description = str(entity.get("error_description") or "")[:255]
    if payment.status == Payment.Status.CAPTURED and payment.paid_at is None:
        payment.paid_at = now
    payment.save()

    # ---- Update the order based on the (possibly unchanged) payment status
    if payment.status == Payment.Status.CAPTURED:
        if order.status != PaymentOrder.Status.PAID:
            order.status = PaymentOrder.Status.PAID
            order.paid_at = now
            order.save(update_fields=["status", "paid_at", "updated_at"])
            logger.info("Order %s marked PAID via %s", order.internal_order_id, source)
        elif order.payments.filter(status=Payment.Status.CAPTURED).exclude(pk=payment.pk).exists():
            # Should never happen (Razorpay blocks new payments on a paid
            # order), but if it does the money must be refunded manually.
            logger.critical(
                "Second captured payment %s on already-paid order %s - manual refund review required.",
                payment_id, order.internal_order_id,
            )
        activate_enrollment_after_payment(order)

    elif payment.status == Payment.Status.AUTHORIZED:
        if order.status in (PaymentOrder.Status.CREATED, PaymentOrder.Status.FAILED):
            order.status = PaymentOrder.Status.PENDING
            order.save(update_fields=["status", "updated_at"])

    elif payment.status == Payment.Status.FAILED:
        if order.status == PaymentOrder.Status.CREATED:
            order.status = PaymentOrder.Status.FAILED
            order.save(update_fields=["status", "updated_at"])
        logger.info("Payment %s failed for order %s", payment_id, order.internal_order_id)

    return PaymentOutcome(order=order, payment=payment, outcome=payment.status)


# =========================================================================
# LMS hook - enrollment activation
# =========================================================================

def activate_enrollment_after_payment(order):
    """
    Activate LMS enrollment for a PAID order - exactly once.

    * Called automatically after a captured payment is recorded.
    * Must run inside ``transaction.atomic()`` with the order row locked.
    * The actual enrollment is delegated to the configured enrollment adapter
      (demo adapter in this project, real LMS adapter in the main project).
    * If the adapter fails, the payment stays recorded as paid and the error
      is logged; run ``python manage.py retry_enrollments`` to retry.

    Returns True if enrollment was activated by this call.
    """
    if order.status != PaymentOrder.Status.PAID or order.enrollment_activated:
        return False
    # Defence in depth: never activate without a captured payment row.
    if not order.payments.filter(status=Payment.Status.CAPTURED).exists():
        logger.error("Refusing to activate enrollment for %s: no captured payment.", order.internal_order_id)
        return False

    course_ids = order.get_course_ids()
    try:
        # Savepoint: if the adapter fails, only its own DB changes roll back.
        with transaction.atomic():
            get_enrollment_adapter().activate_enrollment(
                user=order.user, order=order, course_ids=course_ids
            )
    except Exception:  # noqa: BLE001 - any adapter failure must not lose the payment
        logger.exception(
            "Enrollment activation failed for paid order %s. Payment is recorded; "
            "run 'python manage.py retry_enrollments' after fixing the cause.",
            order.internal_order_id,
        )
        return False

    order.enrollment_activated = True
    order.enrollment_activated_at = timezone.now()
    order.save(update_fields=["enrollment_activated", "enrollment_activated_at", "updated_at"])
    logger.info("Enrollment activated for order %s (courses=%s)", order.internal_order_id, course_ids)
    return True


# =========================================================================
# API 2 - Verify checkout payment
# =========================================================================

def get_order_for_user(user, razorpay_order_id):
    """Return the user's order or raise OrderNotFoundError (also for other users' orders)."""
    order = PaymentOrder.objects.filter(user=user, razorpay_order_id=razorpay_order_id).first()
    if order is None:
        raise OrderNotFoundError()
    return order


def verify_checkout_payment(*, user, razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Verify a payment reported by Razorpay Checkout in the browser.

    Steps: ownership -> checkout signature -> fetch payment from Razorpay ->
    match order/amount/currency -> (optional) capture -> record -> enrollment.
    """
    key_secret = conf.get_razorpay_key_secret()
    order = get_order_for_user(user, razorpay_order_id)

    # 1) Checkout signature: proves the ids came from Razorpay Checkout.
    if not verify_checkout_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature, key_secret):
        logger.warning("Invalid checkout signature for order %s", order.internal_order_id)
        raise SignatureVerificationFailed()

    # 2) Already recorded as captured (e.g. webhook arrived first)? Then no
    #    need to call Razorpay again - just make sure enrollment happened.
    existing = Payment.objects.filter(razorpay_payment_id=razorpay_payment_id).first()
    if existing is not None and existing.order_id != order.pk:
        logger.error("Payment %s belongs to a different order.", razorpay_payment_id)
        raise PaymentMismatchError()
    if existing is not None and existing.status == Payment.Status.CAPTURED:
        with transaction.atomic():
            locked = PaymentOrder.objects.select_for_update().get(pk=order.pk)
            activate_enrollment_after_payment(locked)
        existing.refresh_from_db()
        return PaymentOutcome(order=locked, payment=existing, outcome=existing.status)

    # 3) The signature alone does NOT prove the money was captured.
    #    Ask Razorpay for the real payment state.
    gateway = get_gateway()
    entity = gateway.fetch_payment(razorpay_payment_id)
    _validate_payment_matches_order(order, entity)

    # 4) Authorized but not captured (auto-capture disabled in Dashboard):
    #    optionally capture it now, for exactly the order amount.
    if entity.get("status") == "authorized" and conf.capture_authorized_payments():
        try:
            entity = gateway.capture_payment(razorpay_payment_id, order.amount, order.currency)
        except GatewayError:
            # e.g. Razorpay auto-captured it a moment ago. Re-read the real state.
            logger.warning("Capture failed for %s; re-fetching payment state.", razorpay_payment_id)
            try:
                entity = gateway.fetch_payment(razorpay_payment_id)
            except GatewayError:
                pass  # keep the authorized state; webhook will finish the job

    # 5) Record the result atomically with the order row locked.
    with transaction.atomic():
        locked = PaymentOrder.objects.select_for_update().get(pk=order.pk)
        return apply_payment_entity(locked, entity, source="verify_api")


# =========================================================================
# API 3 - Webhook
# =========================================================================

def _handle_webhook_event(event_type, payment_entity, order_entity, razorpay_order_id):
    """
    Process one verified webhook event. Runs inside the caller's transaction.
    Returns (WebhookEvent.Status, message).
    """
    if event_type not in HANDLED_WEBHOOK_EVENTS:
        return WebhookEvent.Status.IGNORED, "Event type not handled."
    if not payment_entity or not razorpay_order_id:
        return WebhookEvent.Status.IGNORED, "Event has no payment/order information."

    order = PaymentOrder.objects.select_for_update().filter(razorpay_order_id=razorpay_order_id).first()
    if order is None:
        # e.g. an order created by another system on the same Razorpay account.
        logger.info("Webhook %s for unknown order %s ignored.", event_type, razorpay_order_id)
        return WebhookEvent.Status.IGNORED, "Order not managed by this module."

    try:
        if order_entity:  # order.paid also carries the order entity
            if (
                order_entity.get("id") != order.razorpay_order_id
                or int(order_entity.get("amount", -1)) != order.amount
                or str(order_entity.get("currency", "")).upper() != order.currency
            ):
                raise PaymentMismatchError("Order details in webhook do not match.")
        with transaction.atomic():  # savepoint
            outcome = apply_payment_entity(order, payment_entity, source=f"webhook:{event_type}")
    except PaymentMismatchError as exc:
        logger.error("Webhook %s rejected for order %s: %s", event_type, order.internal_order_id, exc.message)
        return WebhookEvent.Status.FAILED, exc.message

    return WebhookEvent.Status.PROCESSED, f"Payment {outcome.outcome}."


def process_webhook(*, raw_body, signature, event_id=None):
    """
    Verify and process a Razorpay webhook.

    ``raw_body`` must be the exact bytes received (``request.body``).
    Duplicate deliveries (same event id) are acknowledged without
    re-processing.
    """
    webhook_secret = conf.get_webhook_secret()

    # Webhook signature = HMAC of the RAW body with the WEBHOOK secret.
    # (Different from the checkout signature!)
    if not verify_webhook_signature(raw_body, signature, webhook_secret):
        logger.warning("Rejected webhook with invalid signature.")
        raise SignatureVerificationFailed("Invalid webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PaymentError("Malformed webhook payload.") from exc

    event_type = str(payload.get("event", ""))[:64]
    body = payload.get("payload") or {}
    payment_entity = ((body.get("payment") or {}).get("entity")) or {}
    order_entity = ((body.get("order") or {}).get("entity")) or {}
    razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id") or ""
    razorpay_payment_id = payment_entity.get("id") or ""

    # Razorpay sends a unique X-Razorpay-Event-Id header. If it is missing we
    # fall back to a hash of the body, which is identical for redeliveries.
    event_id = (event_id or "").strip()[:128] or f"sha256:{hashlib.sha256(raw_body).hexdigest()[:100]}"

    try:
        with transaction.atomic():
            event, created = WebhookEvent.objects.select_for_update().get_or_create(
                event_id=event_id,
                defaults={
                    "event_type": event_type,
                    "razorpay_order_id": str(razorpay_order_id)[:64],
                    "razorpay_payment_id": str(razorpay_payment_id)[:64],
                },
            )
            if not created:
                if event.status in (WebhookEvent.Status.PROCESSED, WebhookEvent.Status.IGNORED):
                    logger.info("Duplicate webhook %s (%s) ignored.", event_id, event_type)
                    return WebhookResult(200, True, "Duplicate event - already processed.", "duplicate")
                event.attempts += 1  # previous attempt failed -> retry

            status, message = _handle_webhook_event(
                event_type, payment_entity, order_entity, razorpay_order_id
            )
            event.status = status
            event.error_message = message[:255] if status == WebhookEvent.Status.FAILED else ""
            event.processed_at = timezone.now()
            event.save()
    except Exception as exc:  # noqa: BLE001
        # Unexpected error (e.g. database problem). Everything above was rolled
        # back. Record the failure and return 500 so Razorpay retries later.
        logger.exception("Webhook %s (%s) processing error.", event_id, event_type)
        WebhookEvent.objects.update_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type,
                "status": WebhookEvent.Status.FAILED,
                "razorpay_order_id": str(razorpay_order_id)[:64],
                "razorpay_payment_id": str(razorpay_payment_id)[:64],
                "error_message": f"Unexpected error: {exc.__class__.__name__}",
            },
        )
        return WebhookResult(500, False, "Webhook processing failed and will be retried.", "failed")

    if status == WebhookEvent.Status.FAILED:
        # Validation failures will not fix themselves on retry, so we
        # acknowledge (200) and leave the event marked FAILED for review.
        return WebhookResult(200, False, f"Event rejected: {message}", status)
    return WebhookResult(200, True, message, status)
