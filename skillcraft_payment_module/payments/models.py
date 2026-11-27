"""
Database models for the SkillCraft.AI payments module.

Three tables:

* PaymentOrder  - one row per Razorpay order (what the student is buying and
                  how much it costs). Created by the Create Order API.
* Payment       - one row per Razorpay payment attempt on an order. A student
                  can retry a failed payment on the same order, so an order can
                  have several payments, but each Razorpay payment id appears
                  only once (unique constraint -> no duplicate payments).
* WebhookEvent  - one row per Razorpay webhook event id. Used for idempotency:
                  the same event delivered twice is processed only once.

LMS INTEGRATION NOTE
--------------------
These models intentionally do NOT have foreign keys to Course / Enrollment
models, because those live in the main SkillCraft.AI project. Courses are
referenced by an identifier string (`course_id`, `included_course_ids`).
The user is referenced through ``settings.AUTH_USER_MODEL``, so the main
project's custom User model is used automatically.
See docs/MAIN_PROJECT_INTEGRATION.md.
"""
import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .compat import check_constraint


class PurchaseType(models.TextChoices):
    COURSE = "course", "Individual Course"
    COMBO = "combo", "Complete Combo Package"


def generate_internal_order_id():
    """
    Human friendly, unguessable internal order id, e.g. ``SCO20261127A1B2C3D4E5``.
    Also used as the Razorpay ``receipt`` (Razorpay limit: 40 characters).
    """
    return f"SCO{timezone.now():%Y%m%d}{secrets.token_hex(5).upper()}"


class PaymentOrder(models.Model):
    """A purchase order created in Razorpay for one student."""

    class Status(models.TextChoices):
        CREATED = "created", "Created (awaiting payment)"
        PENDING = "pending", "Pending (authorized, awaiting capture)"
        PAID = "paid", "Paid (payment captured)"
        FAILED = "failed", "Failed (last payment attempt failed)"

    internal_order_id = models.CharField(
        max_length=40,
        unique=True,
        default=generate_internal_order_id,
        editable=False,
        help_text="Internal SkillCraft order id (also sent to Razorpay as receipt).",
    )
    razorpay_order_id = models.CharField(
        max_length=64, unique=True, help_text="Order id returned by Razorpay (order_xxx)."
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # financial records must never be cascade-deleted
        related_name="razorpay_payment_orders",
    )
    purchase_type = models.CharField(max_length=16, choices=PurchaseType.choices)
    # LMS mapping: identifier of the real Course (primary key, slug, UUID ...).
    # Empty for combo purchases.
    course_id = models.CharField(max_length=64, blank=True, default="")
    course_title = models.CharField(
        max_length=255, blank=True, default="", help_text="Snapshot for display."
    )
    # Snapshot of the course identifiers this order grants access to.
    # (individual -> [course_id]; combo -> the combo mapping at purchase time)
    included_course_ids = models.JSONField(default=list, blank=True)

    amount = models.PositiveBigIntegerField(help_text="Amount in paise (1 INR = 100 paise).")
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)

    paid_at = models.DateTimeField(null=True, blank=True)
    enrollment_activated = models.BooleanField(default=False)
    enrollment_activated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="payorder_user_created_idx"),
            models.Index(fields=["user", "status"], name="payorder_user_status_idx"),
        ]
        constraints = [
            check_constraint(Q(amount__gt=0), name="payorder_amount_positive"),
            check_constraint(
                Q(status__in=["created", "pending", "paid", "failed"]),
                name="payorder_status_valid",
            ),
            # An individual purchase must have a course id; a combo must not.
            check_constraint(
                (Q(purchase_type="course") & ~Q(course_id=""))
                | (Q(purchase_type="combo") & Q(course_id="")),
                name="payorder_course_id_matches_type",
            ),
        ]

    def __str__(self):
        return f"{self.internal_order_id} ({self.purchase_type}, {self.status})"

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    def get_course_ids(self):
        """Course identifiers granted by this order (used by the enrollment adapter)."""
        if self.included_course_ids:
            return [str(cid) for cid in self.included_course_ids]
        return [self.course_id] if self.course_id else []

    def primary_payment(self):
        """
        The payment that best represents this order: the captured one if any,
        otherwise the most recent attempt. Works with prefetch_related().
        """
        payments = list(self.payments.all())
        if not payments:
            return None
        for payment in payments:
            if payment.status == Payment.Status.CAPTURED:
                return payment
        return max(payments, key=lambda p: p.created_at)


class Payment(models.Model):
    """One Razorpay payment attempt (pay_xxx) for an order."""

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        AUTHORIZED = "authorized", "Authorized (not yet captured)"
        CAPTURED = "captured", "Captured (money received)"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    # A payment status may only move "forward" in this ranking. This protects
    # against out-of-order webhooks (e.g. a late "failed" after "captured").
    STATUS_RANK = {
        Status.CREATED: 0,
        Status.FAILED: 1,  # Razorpay "late authorisation" can move failed -> authorized
        Status.AUTHORIZED: 2,
        Status.CAPTURED: 3,
        Status.REFUNDED: 4,
    }

    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT, related_name="payments")
    razorpay_payment_id = models.CharField(max_length=64, unique=True)
    amount = models.PositiveBigIntegerField(help_text="Amount in paise.")
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    method = models.CharField(max_length=32, blank=True, default="", help_text="card, upi, netbanking ...")
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_description = models.CharField(max_length=255, blank=True, default="")
    source = models.CharField(
        max_length=40, blank=True, default="", help_text="Last update source: verify_api / webhook:<event>."
    )
    paid_at = models.DateTimeField(null=True, blank=True, help_text="When the capture was recorded.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            check_constraint(Q(amount__gt=0), name="payment_amount_positive"),
            check_constraint(
                Q(status__in=["created", "authorized", "captured", "failed", "refunded"]),
                name="payment_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.razorpay_payment_id} ({self.status})"


class WebhookEvent(models.Model):
    """A Razorpay webhook delivery, stored for idempotency and auditing."""

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        FAILED = "failed", "Failed"

    event_id = models.CharField(max_length=128, unique=True, help_text="X-Razorpay-Event-Id header.")
    event_type = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    # Only identifiers are stored - never the full payload (which can contain
    # customer email, phone and card details).
    razorpay_order_id = models.CharField(max_length=64, blank=True, default="")
    razorpay_payment_id = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=255, blank=True, default="")
    attempts = models.PositiveIntegerField(default=1)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.event_type} {self.event_id} ({self.status})"
