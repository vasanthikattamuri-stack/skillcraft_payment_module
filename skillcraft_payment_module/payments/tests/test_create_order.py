"""Tests for API 1 - POST /api/payments/create-order/."""
from django.test import override_settings

from payments.exceptions import GatewayError
from payments.models import PaymentOrder

from .utils import TEST_KEY_ID, TEST_KEY_SECRET, PaymentTestCase, RecordingEnrollmentAdapter

URL = "/api/payments/create-order/"


class CreateOrderTests(PaymentTestCase):
    # 1. Individual course order creation
    def test_create_individual_course_order(self):
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["message"], "Order created successfully")
        data = body["data"]
        self.assertEqual(data["amount"], 500000)  # Rs 5,000 in paise
        self.assertEqual(data["amount_inr"], "5000.00")
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["purchase_type"], "course")
        self.assertEqual(data["course_id"], "12")
        self.assertEqual(data["razorpay_key_id"], TEST_KEY_ID)
        self.assertTrue(data["razorpay_order_id"].startswith("order_"))
        self.assertTrue(data["internal_order_id"].startswith("SCO"))
        # The secret key must never be sent to the client.
        self.assertNotIn(TEST_KEY_SECRET, response.content.decode())

        order = PaymentOrder.objects.get(razorpay_order_id=data["razorpay_order_id"])
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.amount, 500000)
        self.assertEqual(order.status, PaymentOrder.Status.CREATED)
        self.assertEqual(order.included_course_ids, ["12"])

        kwargs = self.gateway.create_order.call_args.kwargs
        self.assertEqual(kwargs["amount"], 500000)
        self.assertEqual(kwargs["currency"], "INR")
        self.assertEqual(kwargs["receipt"], order.internal_order_id)

    # 2. Combo order creation
    def test_create_combo_order(self):
        response = self.client.post(URL, {"purchase_type": "combo"}, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["amount"], 2000000)  # Rs 20,000 in paise
        self.assertEqual(data["purchase_type"], "combo")
        self.assertIsNone(data["course_id"])
        order = PaymentOrder.objects.get(razorpay_order_id=data["razorpay_order_id"])
        self.assertEqual(order.included_course_ids, ["11", "12", "13"])
        self.assertEqual(self.gateway.create_order.call_args.kwargs["amount"], 2000000)

    @override_settings(PAYMENTS_COMBO_COURSE_IDS=[])
    def test_combo_refused_when_mapping_not_configured(self):
        response = self.client.post(URL, {"purchase_type": "combo"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["success"])
        self.gateway.create_order.assert_not_called()

    # 3. Invalid purchase type
    def test_invalid_purchase_type(self):
        for bad in ["premium", "", None, 123]:
            response = self.client.post(URL, {"purchase_type": bad, "course_id": 12}, format="json")
            self.assertEqual(response.status_code, 400, bad)
            self.assertFalse(response.json()["success"])
            self.assertIn("purchase_type", response.json()["errors"])
        self.gateway.create_order.assert_not_called()
        self.assertEqual(PaymentOrder.objects.count(), 0)

    # 4. Invalid course identifier
    def test_invalid_course_identifier(self):
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 999}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("course_id", response.json()["errors"])
        self.gateway.create_order.assert_not_called()

    def test_course_id_required_for_individual_purchase(self):
        response = self.client.post(URL, {"purchase_type": "course"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("course_id", response.json()["errors"])

    def test_course_id_not_allowed_for_combo(self):
        response = self.client.post(URL, {"purchase_type": "combo", "course_id": 12}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("course_id", response.json()["errors"])

    # 5. Backend price validation - client supplied amounts are ignored
    def test_client_supplied_amount_is_ignored(self):
        response = self.client.post(
            URL, {"purchase_type": "course", "course_id": 12, "amount": 1, "currency": "USD"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["amount"], 500000)
        self.assertEqual(response.json()["data"]["currency"], "INR")

        response = self.client.post(URL, {"purchase_type": "combo", "amount": 100}, format="json")
        self.assertEqual(response.json()["data"]["amount"], 2000000)
        amounts = sorted(PaymentOrder.objects.values_list("amount", flat=True))
        self.assertEqual(amounts, [500000, 2000000])

    def test_gateway_amount_mismatch_is_rejected(self):
        self.gateway.create_order.side_effect = None
        self.gateway.create_order.return_value = {"id": "order_Wrong1", "amount": 100, "currency": "INR"}
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(PaymentOrder.objects.count(), 0)

    def test_gateway_failure_returns_safe_error(self):
        self.gateway.create_order.side_effect = GatewayError()
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["success"])
        self.assertEqual(PaymentOrder.objects.count(), 0)

    @override_settings(RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
    def test_missing_credentials_returns_503(self):
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")
        # Order creation reaches the gateway mock, but returning the public
        # key requires configuration -> safe 503.
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["message"], "Payment gateway is not configured.")

    def test_recent_unpaid_identical_order_is_reused(self):
        first = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")
        second = self.client.post(URL, {"purchase_type": "course", "course_id": "12"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["data"]["reused_existing_order"])
        self.assertEqual(first.json()["data"]["razorpay_order_id"], second.json()["data"]["razorpay_order_id"])
        self.assertEqual(self.gateway.create_order.call_count, 1)

    def test_cannot_buy_already_purchased_course(self):
        self.make_order(course_id="12", status=PaymentOrder.Status.PAID)
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 12}, format="json")
        self.assertEqual(response.status_code, 409)
        self.gateway.create_order.assert_not_called()

    def test_cannot_buy_course_included_in_paid_combo(self):
        self.make_order(purchase_type="combo", status=PaymentOrder.Status.PAID)
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 13}, format="json")
        self.assertEqual(response.status_code, 409)
        # A course NOT in the combo can still be bought.
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 15}, format="json")
        self.assertEqual(response.status_code, 201)

    def test_cannot_buy_when_lms_reports_existing_access(self):
        RecordingEnrollmentAdapter.access = {(self.user.pk, "14")}
        response = self.client.post(URL, {"purchase_type": "course", "course_id": 14}, format="json")
        self.assertEqual(response.status_code, 409)
