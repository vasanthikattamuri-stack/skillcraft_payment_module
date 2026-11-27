"""Tests for API 4 - GET /api/payments/status/<razorpay_order_id>/."""
from payments.models import Payment, PaymentOrder

from .utils import PaymentTestCase


class PaymentStatusTests(PaymentTestCase):
    # 10. Payment status retrieval
    def test_get_payment_status_for_created_order(self):
        order = self.make_order()
        url = f"/api/payments/status/{order.razorpay_order_id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertEqual(data["internal_order_id"], order.internal_order_id)
        self.assertEqual(data["razorpay_order_id"], order.razorpay_order_id)
        self.assertEqual(data["purchase_type"], "course")
        self.assertEqual(data["amount"], 500000)
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["order_status"], "created")
        self.assertIsNone(data["payment_status"])
        self.assertIsNone(data["payment_method"])

    def test_get_payment_status_for_paid_order(self):
        order = self.make_order(status=PaymentOrder.Status.PAID)
        Payment.objects.create(
            order=order,
            razorpay_payment_id="pay_StatusPaid001",
            amount=order.amount,
            currency="INR",
            status=Payment.Status.CAPTURED,
            method="card",
        )
        url = f"/api/payments/status/{order.razorpay_order_id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["order_status"], "paid")
        self.assertEqual(data["payment_status"], "captured")
        self.assertEqual(data["payment_method"], "card")

    # 9. Order ownership validation - status endpoint
    def test_cannot_view_another_users_order_status(self):
        order = self.make_order(user=self.other_user)
        url = f"/api/payments/status/{order.razorpay_order_id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_order_returns_404(self):
        response = self.client.get("/api/payments/status/order_DoesNotExist/")
        self.assertEqual(response.status_code, 404)

    # 8. Unauthorized access
    def test_unauthenticated_request_is_rejected(self):
        order = self.make_order()
        self.client.force_authenticate(None)
        url = f"/api/payments/status/{order.razorpay_order_id}/"
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])

    def test_status_does_not_expose_sensitive_data(self):
        order = self.make_order(status=PaymentOrder.Status.PAID)
        Payment.objects.create(
            order=order,
            razorpay_payment_id="pay_StatusCheck001",
            amount=order.amount,
            currency="INR",
            status=Payment.Status.CAPTURED,
            method="upi",
        )
        url = f"/api/payments/status/{order.razorpay_order_id}/"
        response = self.client.get(url)
        content = response.content.decode()
        # Must not contain the secret key
        from .utils import TEST_KEY_SECRET, TEST_WEBHOOK_SECRET
        self.assertNotIn(TEST_KEY_SECRET, content)
        self.assertNotIn(TEST_WEBHOOK_SECRET, content)
