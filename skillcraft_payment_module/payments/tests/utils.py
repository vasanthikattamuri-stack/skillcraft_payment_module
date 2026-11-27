"""
Shared helpers for the payments test suite.

* Razorpay is NEVER called: ``payments.services.get_gateway`` is patched with
  a mock in every test.
* The credentials below are fake values that exist only inside the tests.
"""
import itertools
import json

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from unittest.mock import patch

from payments.adapters.base import BaseEnrollmentAdapter
from payments.models import PaymentOrder
from payments.signatures import generate_checkout_signature, generate_webhook_signature

TEST_KEY_ID = "rzp_test_UnitTestKeyId"
TEST_KEY_SECRET = "unit-test-key-secret-not-real"
TEST_WEBHOOK_SECRET = "unit-test-webhook-secret-not-real"

PAYMENT_TEST_SETTINGS = {
    "RAZORPAY_KEY_ID": TEST_KEY_ID,
    "RAZORPAY_KEY_SECRET": TEST_KEY_SECRET,
    "RAZORPAY_WEBHOOK_SECRET": TEST_WEBHOOK_SECRET,
    "PAYMENTS_COURSE_CATALOG_ADAPTER": "payments.adapters.demo.DemoCourseCatalogAdapter",
    "PAYMENTS_ENROLLMENT_ADAPTER": "payments.tests.utils.RecordingEnrollmentAdapter",
    "PAYMENTS_COMBO_COURSE_IDS": ["11", "12", "13"],
    "PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS": True,
    "PAYMENTS_ORDER_REUSE_MINUTES": 30,
}

_ids = itertools.count(1)


def unique_suffix():
    return f"T{next(_ids):06d}"


class RecordingEnrollmentAdapter(BaseEnrollmentAdapter):
    """Test adapter that records every activation call."""

    calls = []
    access = set()  # {(user_pk, course_id)} the user "already has"

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.access = set()

    def user_has_access(self, *, user, course_ids):
        return bool(course_ids) and all((user.pk, cid) in self.access for cid in course_ids)

    def activate_enrollment(self, *, user, order, course_ids):
        RecordingEnrollmentAdapter.calls.append(
            {"user_id": user.pk, "order": order.internal_order_id, "course_ids": list(course_ids)}
        )


class FailingEnrollmentAdapter(BaseEnrollmentAdapter):
    """Test adapter that always fails (simulates an LMS outage)."""

    def activate_enrollment(self, *, user, order, course_ids):
        raise RuntimeError("LMS database unavailable")


@override_settings(**PAYMENT_TEST_SETTINGS)
class PaymentTestCase(APITestCase):
    """Base class: two users, an authenticated client and a mocked gateway."""

    def setUp(self):
        RecordingEnrollmentAdapter.reset()
        User = get_user_model()
        self.user = User.objects.create_user(username="student1", password="Str0ngPass!123")
        self.other_user = User.objects.create_user(username="student2", password="Str0ngPass!123")
        self.client.force_authenticate(self.user)

        patcher = patch("payments.services.get_gateway")
        self.gateway = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.gateway.create_order.side_effect = self._fake_create_order

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _fake_create_order(*, amount, currency, receipt, notes=None):
        return {
            "id": f"order_{unique_suffix()}",
            "entity": "order",
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
        }

    @property
    def enrollment_calls(self):
        return RecordingEnrollmentAdapter.calls

    def make_order(self, user=None, purchase_type="course", course_id="12", status=PaymentOrder.Status.CREATED):
        amount = 500000 if purchase_type == "course" else 2000000
        included = [course_id] if purchase_type == "course" else ["11", "12", "13"]
        return PaymentOrder.objects.create(
            razorpay_order_id=f"order_{unique_suffix()}",
            user=user or self.user,
            purchase_type=purchase_type,
            course_id=course_id if purchase_type == "course" else "",
            course_title="DEMO",
            included_course_ids=included,
            amount=amount,
            currency="INR",
            status=status,
        )

    @staticmethod
    def payment_entity(order, payment_id="pay_TestPayment001", status="captured", amount=None,
                       currency="INR", order_id=None, method="upi", **extra):
        entity = {
            "id": payment_id,
            "entity": "payment",
            "amount": order.amount if amount is None else amount,
            "currency": currency,
            "status": status,
            "order_id": order.razorpay_order_id if order_id is None else order_id,
            "method": method,
            "captured": status == "captured",
        }
        entity.update(extra)
        return entity

    @staticmethod
    def checkout_signature(order_id, payment_id, secret=TEST_KEY_SECRET):
        return generate_checkout_signature(order_id, payment_id, secret)

    def verify(self, order, payment_id="pay_TestPayment001", signature=None):
        return self.client.post(
            "/api/payments/verify/",
            {
                "razorpay_order_id": order.razorpay_order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature or self.checkout_signature(order.razorpay_order_id, payment_id),
            },
            format="json",
        )

    @staticmethod
    def webhook_payload(event, payment_entity=None, order_entity=None):
        payload = {}
        contains = []
        if payment_entity is not None:
            payload["payment"] = {"entity": payment_entity}
            contains.append("payment")
        if order_entity is not None:
            payload["order"] = {"entity": order_entity}
            contains.append("order")
        return {
            "entity": "event",
            "account_id": "acc_TestAccount",
            "event": event,
            "contains": contains,
            "payload": payload,
            "created_at": 1700000000,
        }

    def post_webhook(self, payload, event_id="evt_Test001", signature=None, raw_body=None, secret=TEST_WEBHOOK_SECRET):
        raw = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
        headers = {"HTTP_X_RAZORPAY_SIGNATURE": signature or generate_webhook_signature(raw, secret)}
        if event_id:
            headers["HTTP_X_RAZORPAY_EVENT_ID"] = event_id
        # Webhooks come from Razorpay servers - no logged-in user.
        self.client.force_authenticate(None)
        try:
            return self.client.post(
                "/api/payments/webhook/", data=raw, content_type="application/json", **headers
            )
        finally:
            self.client.force_authenticate(self.user)
