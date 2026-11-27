"""Tests for API 3 - POST /api/payments/webhook/ and idempotency."""
import json

from payments.models import Payment, PaymentOrder, WebhookEvent

from .utils import PaymentTestCase, TEST_WEBHOOK_SECRET


class WebhookSignatureTests(PaymentTestCase):
    # 12. Webhook signature verification
    def test_valid_webhook_signature_is_accepted(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)
        response = self.post_webhook(payload, event_id="evt_Valid001")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["success"])

    def test_invalid_webhook_signature_is_rejected(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)
        response = self.post_webhook(payload, event_id="evt_Bad001", signature="bad_signature")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_missing_signature_header_is_rejected(self):
        payload = self.webhook_payload("payment.captured")
        raw = json.dumps(payload).encode("utf-8")
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/payments/webhook/",
            data=raw,
            content_type="application/json",
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(response.status_code, 400)

    def test_webhook_uses_webhook_secret_not_key_secret(self):
        """The webhook signature must be verified with RAZORPAY_WEBHOOK_SECRET,
        not with RAZORPAY_KEY_SECRET (they are different keys)."""
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)
        # Sign with the checkout key secret instead of the webhook secret
        from payments.signatures import generate_webhook_signature
        from .utils import TEST_KEY_SECRET
        wrong_signature = generate_webhook_signature(
            json.dumps(payload).encode("utf-8"), TEST_KEY_SECRET
        )
        response = self.post_webhook(payload, event_id="evt_WrongKey", signature=wrong_signature)
        self.assertEqual(response.status_code, 400)


class WebhookIdempotencyTests(PaymentTestCase):
    # 13. Duplicate webhook delivery
    def test_duplicate_webhook_is_acknowledged_but_not_reprocessed(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        first = self.post_webhook(payload, event_id="evt_Dup001")
        second = self.post_webhook(payload, event_id="evt_Dup001")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIn("Duplicate", second.json()["message"])
        # Only one WebhookEvent record and one Payment record
        self.assertEqual(WebhookEvent.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        # Enrollment only triggered once
        self.assertEqual(len(self.enrollment_calls), 1)

    def test_different_event_ids_are_processed_independently(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        first = self.post_webhook(payload, event_id="evt_A001")
        second = self.post_webhook(payload, event_id="evt_A002")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WebhookEvent.objects.count(), 2)
        # But still only one payment (same razorpay_payment_id)
        self.assertEqual(Payment.objects.count(), 1)


class WebhookPaymentCapturedTests(PaymentTestCase):
    # 14. Successful captured payment processing via webhook
    def test_payment_captured_webhook_updates_order_to_paid(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        response = self.post_webhook(payload, event_id="evt_Cap001")

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertIsNotNone(order.paid_at)
        payment = Payment.objects.get(razorpay_payment_id="pay_TestPayment001")
        self.assertEqual(payment.status, Payment.Status.CAPTURED)
        # 16. Enrollment activated after captured payment
        self.assertEqual(len(self.enrollment_calls), 1)
        self.assertEqual(self.enrollment_calls[0]["course_ids"], ["12"])

    def test_webhook_before_verify_api_still_works(self):
        """Webhook arriving before the frontend calls the verify API should
        still correctly update the order and activate enrollment."""
        order = self.make_order()
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        self.post_webhook(payload, event_id="evt_Early001")

        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertTrue(order.enrollment_activated)

        # Now when verify is called, it should handle the already-captured payment
        self.gateway.fetch_payment.return_value = entity
        response = self.verify(order)
        self.assertEqual(response.status_code, 200)
        # No duplicate enrollment
        self.assertEqual(len(self.enrollment_calls), 1)

    def test_webhook_validates_amount(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured", amount=100)
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        response = self.post_webhook(payload, event_id="evt_BadAmt001")

        self.assertEqual(response.status_code, 200)  # acknowledged
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)
        self.assertEqual(Payment.objects.count(), 0)

    def test_webhook_validates_currency(self):
        order = self.make_order()
        entity = self.payment_entity(order, status="captured", currency="USD")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)

        response = self.post_webhook(payload, event_id="evt_BadCur001")

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)

    def test_webhook_for_unknown_order_is_ignored(self):
        entity = {
            "id": "pay_Unknown001",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "order_id": "order_DoesNotExist",
            "method": "upi",
        }
        payload = self.webhook_payload("payment.captured", payment_entity=entity)
        response = self.post_webhook(payload, event_id="evt_NoOrder001")
        self.assertEqual(response.status_code, 200)
        event = WebhookEvent.objects.get(event_id="evt_NoOrder001")
        self.assertEqual(event.status, WebhookEvent.Status.IGNORED)


class WebhookPaymentFailedTests(PaymentTestCase):
    # 15. Failed payment processing via webhook
    def test_payment_failed_webhook_updates_order(self):
        order = self.make_order()
        entity = self.payment_entity(
            order, status="failed",
            error_code="BAD_REQUEST_ERROR",
            error_description="Card declined",
        )
        payload = self.webhook_payload("payment.failed", payment_entity=entity)

        response = self.post_webhook(payload, event_id="evt_Fail001")

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.FAILED)
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        # No enrollment for failed payments
        self.assertEqual(self.enrollment_calls, [])


class WebhookOrderPaidTests(PaymentTestCase):
    def test_order_paid_webhook_confirms_order_status(self):
        order = self.make_order()
        # First mark paid via payment.captured
        entity = self.payment_entity(order, status="captured")
        payload = self.webhook_payload("payment.captured", payment_entity=entity)
        self.post_webhook(payload, event_id="evt_Cap002")

        # Then order.paid arrives
        order_entity = {
            "id": order.razorpay_order_id,
            "amount": order.amount,
            "currency": order.currency,
            "status": "paid",
        }
        payload = self.webhook_payload("order.paid", payment_entity=entity, order_entity=order_entity)
        response = self.post_webhook(payload, event_id="evt_OrdPaid001")
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)

    def test_unhandled_webhook_event_type_is_ignored(self):
        payload = self.webhook_payload("refund.created")
        response = self.post_webhook(payload, event_id="evt_Unhandled001")
        self.assertEqual(response.status_code, 200)
        event = WebhookEvent.objects.get(event_id="evt_Unhandled001")
        self.assertEqual(event.status, WebhookEvent.Status.IGNORED)
