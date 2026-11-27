"""Tests for API 2 - POST /api/payments/verify/ and enrollment activation."""
from django.core.management import call_command
from django.test import override_settings

from payments.exceptions import GatewayError
from payments.models import Payment, PaymentOrder

from .utils import PaymentTestCase


class VerifyPaymentTests(PaymentTestCase):
    # 6. Successful checkout signature verification (+ captured payment)
    def test_successful_verification_of_captured_payment(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="captured")

        response = self.verify(order)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["order_status"], "paid")
        self.assertEqual(body["data"]["payment_status"], "captured")
        self.assertTrue(body["data"]["enrollment_activated"])

        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertIsNotNone(order.paid_at)
        payment = Payment.objects.get(razorpay_payment_id="pay_TestPayment001")
        self.assertEqual(payment.status, Payment.Status.CAPTURED)
        self.assertEqual(payment.amount, 500000)
        self.assertEqual(payment.method, "upi")
        self.gateway.fetch_payment.assert_called_once_with("pay_TestPayment001")
        # 16. Enrollment adapter invoked once, after capture.
        self.assertEqual(len(self.enrollment_calls), 1)
        self.assertEqual(self.enrollment_calls[0]["course_ids"], ["12"])

    def test_combo_payment_enrolls_all_combo_courses(self):
        order = self.make_order(purchase_type="combo")
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="captured")
        response = self.verify(order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.enrollment_calls[0]["course_ids"], ["11", "12", "13"])

    # 7. Invalid checkout signature
    def test_invalid_signature_is_rejected(self):
        order = self.make_order()
        bad_signature = self.checkout_signature(order.razorpay_order_id, "pay_TestPayment001", secret="wrong")

        response = self.verify(order, signature=bad_signature)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["message"], "Payment signature verification failed.")
        self.gateway.fetch_payment.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.enrollment_calls, [])

    def test_signature_for_different_payment_is_rejected(self):
        order = self.make_order()
        signature = self.checkout_signature(order.razorpay_order_id, "pay_SomeOtherPayment")
        response = self.verify(order, payment_id="pay_TestPayment001", signature=signature)
        self.assertEqual(response.status_code, 400)

    def test_malformed_input_is_rejected(self):
        response = self.client.post(
            "/api/payments/verify/",
            {"razorpay_order_id": "bad id", "razorpay_payment_id": "x", "razorpay_signature": "zz"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        self.assertEqual(set(errors), {"razorpay_order_id", "razorpay_payment_id", "razorpay_signature"})

    # 9. Order ownership validation
    def test_cannot_verify_another_users_order(self):
        others_order = self.make_order(user=self.other_user)
        response = self.verify(others_order)
        self.assertEqual(response.status_code, 404)
        self.gateway.fetch_payment.assert_not_called()

    def test_unknown_order_returns_404(self):
        response = self.client.post(
            "/api/payments/verify/",
            {
                "razorpay_order_id": "order_DoesNotExist",
                "razorpay_payment_id": "pay_X1",
                "razorpay_signature": "a" * 64,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    # Amount / currency / order validation against Razorpay's data
    def test_amount_mismatch_is_rejected(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, amount=100)
        response = self.verify(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount", response.json()["errors"]["mismatch"])
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.enrollment_calls, [])

    def test_currency_mismatch_is_rejected(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, currency="USD")
        response = self.verify(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn("currency", response.json()["errors"]["mismatch"])

    def test_payment_for_different_order_is_rejected(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, order_id="order_SomethingElse")
        response = self.verify(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn("order_id", response.json()["errors"]["mismatch"])

    # 16. Authorized != captured: no enrollment for authorized payments
    @override_settings(PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS=False)
    def test_authorized_payment_is_not_treated_as_captured(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="authorized")

        response = self.verify(order)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"]["payment_status"], "authorized")
        self.assertEqual(response.json()["data"]["order_status"], "pending")
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PENDING)
        self.assertFalse(order.enrollment_activated)
        self.assertEqual(Payment.objects.get().status, Payment.Status.AUTHORIZED)
        self.gateway.capture_payment.assert_not_called()
        self.assertEqual(self.enrollment_calls, [])

    def test_authorized_payment_is_captured_by_backend_when_enabled(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="authorized")
        self.gateway.capture_payment.return_value = self.payment_entity(order, status="captured")

        response = self.verify(order)

        self.assertEqual(response.status_code, 200)
        self.gateway.capture_payment.assert_called_once_with("pay_TestPayment001", 500000, "INR")
        self.assertEqual(len(self.enrollment_calls), 1)

    def test_capture_error_falls_back_to_refetch(self):
        order = self.make_order()
        self.gateway.fetch_payment.side_effect = [
            self.payment_entity(order, status="authorized"),
            self.payment_entity(order, status="captured"),  # auto-captured meanwhile
        ]
        self.gateway.capture_payment.side_effect = GatewayError()
        response = self.verify(order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.enrollment_calls), 1)

    # 15. Failed payment processing (verify path)
    def test_failed_payment(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(
            order, status="failed", error_code="BAD_REQUEST_ERROR", error_description="Payment declined"
        )
        response = self.verify(order)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Payment failed. Please try again.")
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.FAILED)
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(payment.error_description, "Payment declined")
        self.assertEqual(self.enrollment_calls, [])

    def test_retry_after_failure_succeeds(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, payment_id="pay_First1", status="failed")
        self.verify(order, payment_id="pay_First1")
        self.gateway.fetch_payment.return_value = self.payment_entity(order, payment_id="pay_Second2", status="captured")
        response = self.verify(order, payment_id="pay_Second2")
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertEqual(order.payments.count(), 2)
        self.assertEqual(len(self.enrollment_calls), 1)

    # 11. Duplicate payment prevention
    def test_verifying_twice_does_not_duplicate_payment_or_enrollment(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="captured")

        first = self.verify(order)
        second = self.verify(order)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(len(self.enrollment_calls), 1)
        # Second call is answered from the database - no extra Razorpay call.
        self.assertEqual(self.gateway.fetch_payment.call_count, 1)

    def test_payment_id_cannot_be_reused_for_another_order(self):
        order_a = self.make_order(course_id="11")
        order_b = self.make_order(course_id="12")
        self.gateway.fetch_payment.return_value = self.payment_entity(order_a, status="captured")
        self.assertEqual(self.verify(order_a).status_code, 200)

        response = self.verify(order_b)  # same pay_ id, valid signature for order_b

        self.assertEqual(response.status_code, 400)
        order_b.refresh_from_db()
        self.assertEqual(order_b.status, PaymentOrder.Status.CREATED)
        self.assertEqual(Payment.objects.count(), 1)

    def test_gateway_unavailable_during_verify(self):
        order = self.make_order()
        self.gateway.fetch_payment.side_effect = GatewayError()
        response = self.verify(order)
        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)


class EnrollmentFailureTests(PaymentTestCase):
    @override_settings(PAYMENTS_ENROLLMENT_ADAPTER="payments.tests.utils.FailingEnrollmentAdapter")
    def test_enrollment_failure_keeps_payment_and_can_be_retried(self):
        order = self.make_order()
        self.gateway.fetch_payment.return_value = self.payment_entity(order, status="captured")

        with self.assertLogs("payments", level="ERROR"):
            response = self.verify(order)

        # The payment is still recorded as paid - money is never "lost".
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.PAID)
        self.assertFalse(order.enrollment_activated)

        # Once the LMS is healthy again, the retry command activates it.
        with override_settings(PAYMENTS_ENROLLMENT_ADAPTER="payments.tests.utils.RecordingEnrollmentAdapter"):
            call_command("retry_enrollments", stdout=open("NUL" if __import__("os").name == "nt" else "/dev/null", "w"))
        order.refresh_from_db()
        self.assertTrue(order.enrollment_activated)
        self.assertEqual(len(self.enrollment_calls), 1)
