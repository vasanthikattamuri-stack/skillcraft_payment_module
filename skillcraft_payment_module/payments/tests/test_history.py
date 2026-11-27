"""Tests for API 5 - GET /api/payments/history/."""
from payments.models import Payment, PaymentOrder

from .utils import PaymentTestCase


class PaymentHistoryTests(PaymentTestCase):
    def test_empty_history(self):
        response = self.client.get("/api/payments/history/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["count"], 0)
        self.assertEqual(body["data"]["results"], [])

    def test_returns_only_own_orders(self):
        self.make_order(course_id="11")
        self.make_order(user=self.other_user, course_id="12")

        response = self.client.get("/api/payments/history/")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["course_id"], "11")

    def test_pagination(self):
        # Create 15 orders
        for i in range(15):
            self.make_order(course_id="11")

        response = self.client.get("/api/payments/history/?page=1&page_size=5")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["count"], 15)
        self.assertEqual(len(data["results"]), 5)
        self.assertIsNotNone(data["next"])

        response2 = self.client.get("/api/payments/history/?page=2&page_size=5")
        data2 = response2.json()["data"]
        self.assertEqual(len(data2["results"]), 5)

    def test_includes_payment_status(self):
        order = self.make_order(status=PaymentOrder.Status.PAID)
        Payment.objects.create(
            order=order,
            razorpay_payment_id="pay_History001",
            amount=order.amount,
            currency="INR",
            status=Payment.Status.CAPTURED,
            method="card",
        )
        response = self.client.get("/api/payments/history/")
        result = response.json()["data"]["results"][0]
        self.assertEqual(result["order_status"], "paid")
        self.assertEqual(result["payment_status"], "captured")
        self.assertEqual(result["amount"], 500000)
        self.assertEqual(result["purchase_type"], "course")

    def test_history_ordered_by_newest_first(self):
        o1 = self.make_order(course_id="11")
        o2 = self.make_order(course_id="12")

        response = self.client.get("/api/payments/history/")
        results = response.json()["data"]["results"]
        # Most recent first
        self.assertEqual(results[0]["internal_order_id"], o2.internal_order_id)
        self.assertEqual(results[1]["internal_order_id"], o1.internal_order_id)

    # 8. Unauthorized access
    def test_unauthenticated_history_request_is_rejected(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/payments/history/")
        self.assertIn(response.status_code, [401, 403])

    def test_filter_by_status(self):
        self.make_order(course_id="11", status=PaymentOrder.Status.CREATED)
        self.make_order(course_id="12", status=PaymentOrder.Status.PAID)

        response = self.client.get("/api/payments/history/?status=paid")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["order_status"], "paid")
