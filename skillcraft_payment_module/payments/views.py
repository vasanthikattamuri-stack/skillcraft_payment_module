"""
REST API views for the payments module.

Every response uses the same JSON envelope:

    success: {"success": true,  "message": "...", "data": {...}}
    error:   {"success": false, "message": "...", "errors": {...}}

Views are intentionally thin - the real work happens in services.py.
"""
import logging

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conf, services
from .exceptions import PaymentError
from .models import PaymentOrder
from .pagination import PaymentHistoryPagination
from .permissions import IsOrderOwner
from .pricing import paise_to_inr
from .serializers import (
    CreateOrderSerializer,
    PaymentHistorySerializer,
    PaymentStatusSerializer,
    VerifyPaymentSerializer,
)

logger = logging.getLogger("payments")


def success_response(message, data=None, http_status=status.HTTP_200_OK):
    return Response({"success": True, "message": message, "data": data or {}}, status=http_status)


def error_response(message, http_status=status.HTTP_400_BAD_REQUEST, errors=None, data=None):
    body = {"success": False, "message": message, "errors": errors or {}}
    if data is not None:
        body["data"] = data
    return Response(body, status=http_status)


class PaymentsResponseMixin:
    """Converts every error into the standard envelope with a safe message."""

    def handle_exception(self, exc):
        if isinstance(exc, PaymentError):
            return error_response(exc.message, exc.status_code, exc.errors)

        if isinstance(exc, ImproperlyConfigured):
            logger.error("Payments configuration error: %s", exc)
            return error_response(
                "Payment gateway is not configured.", status.HTTP_503_SERVICE_UNAVAILABLE
            )

        if isinstance(exc, (APIException, Http404, DjangoPermissionDenied)):
            # Standard DRF errors (401, 403, 404, 405, validation 400 ...).
            response = super().handle_exception(exc)
            data = response.data
            if isinstance(data, dict) and set(data.keys()) == {"detail"}:
                message, errors = str(data["detail"]), {}
            else:
                message, errors = "Invalid request data.", data
            response.data = {"success": False, "message": message, "errors": errors}
            return response

        # Unexpected bug: log full details on the server, return a safe message.
        logger.exception("Unexpected error in %s", self.__class__.__name__)
        return error_response(
            "An unexpected error occurred. Please try again later.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class PaymentsAPIView(PaymentsResponseMixin, APIView):
    permission_classes = [IsAuthenticated]


def _order_payload(order, extra=None):
    data = PaymentStatusSerializer(order).data
    if extra:
        data.update(extra)
    return data


# --------------------------------------------------------------------------
# API 1: POST /api/payments/create-order/
# --------------------------------------------------------------------------
class CreateOrderView(PaymentsAPIView):
    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, reused = services.create_payment_order(
            user=request.user,
            purchase_type=serializer.validated_data["purchase_type"],
            course_id=serializer.validated_data.get("course_id"),
        )
        data = {
            "internal_order_id": order.internal_order_id,
            "razorpay_order_id": order.razorpay_order_id,
            "amount": order.amount,  # paise - pass straight to Razorpay Checkout
            "amount_inr": str(paise_to_inr(order.amount)),
            "currency": order.currency,
            "purchase_type": order.purchase_type,
            "course_id": order.course_id or None,
            "course_title": order.course_title,
            "razorpay_key_id": conf.get_razorpay_key_id(),  # PUBLIC key only
            "reused_existing_order": reused,
        }
        if reused:
            return success_response("Existing unpaid order returned", data, status.HTTP_200_OK)
        return success_response("Order created successfully", data, status.HTTP_201_CREATED)


# --------------------------------------------------------------------------
# API 2: POST /api/payments/verify/
# --------------------------------------------------------------------------
class VerifyPaymentView(PaymentsAPIView):
    def post(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = services.verify_checkout_payment(user=request.user, **serializer.validated_data)
        data = _order_payload(result.order)

        if result.outcome == "captured":
            return success_response("Payment verified successfully", data)
        if result.outcome in ("authorized", "created"):
            # NOT a success yet - money is not captured. Access is granted
            # automatically when the payment.captured webhook arrives.
            return success_response(
                "Payment is authorized but not yet captured. Access will be activated "
                "automatically once the payment is captured.",
                data,
                status.HTTP_202_ACCEPTED,
            )
        if result.outcome == "refunded":
            return error_response("This payment has been refunded.", status.HTTP_409_CONFLICT, data=data)
        return error_response(
            "Payment failed. Please try again.", status.HTTP_400_BAD_REQUEST, data=data
        )


# --------------------------------------------------------------------------
# API 3: POST /api/payments/webhook/
# --------------------------------------------------------------------------
class RazorpayWebhookView(PaymentsResponseMixin, APIView):
    """
    Called by Razorpay servers, not by students.

    * No user authentication -> `authentication_classes = []`. Because no
      SessionAuthentication is used, DRF does not enforce CSRF here (DRF
      views are CSRF-exempt by default). Security comes from verifying the
      X-Razorpay-Signature header against the RAW body.
    * We read `request.body` (raw bytes) and never `request.data`, because
      parsing and re-serialising JSON would change the bytes and break the
      signature check.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        raw_body = request.body  # raw bytes - read BEFORE anything else
        result = services.process_webhook(
            raw_body=raw_body,
            signature=request.headers.get("X-Razorpay-Signature", ""),
            event_id=request.headers.get("X-Razorpay-Event-Id"),
        )
        body = {"success": result.success, "message": result.message, "data": {"event_status": result.event_status}}
        return Response(body, status=result.http_status)


# --------------------------------------------------------------------------
# API 4: GET /api/payments/status/<razorpay_order_id>/
# --------------------------------------------------------------------------
class PaymentStatusView(PaymentsAPIView):
    permission_classes = [IsAuthenticated, IsOrderOwner]

    def get(self, request, razorpay_order_id):
        order = (
            PaymentOrder.objects.filter(user=request.user, razorpay_order_id=razorpay_order_id)
            .prefetch_related("payments")
            .first()
        )
        if order is None:
            return error_response("Order not found.", status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, order)  # defence in depth
        return success_response("Payment status fetched successfully", PaymentStatusSerializer(order).data)


# --------------------------------------------------------------------------
# API 5: GET /api/payments/history/?page=1&page_size=10[&status=paid]
# --------------------------------------------------------------------------
class PaymentHistoryView(PaymentsResponseMixin, ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentHistorySerializer
    pagination_class = PaymentHistoryPagination

    def get_queryset(self):
        queryset = (
            PaymentOrder.objects.filter(user=self.request.user)  # ONLY my orders
            .prefetch_related("payments")
            .order_by("-created_at", "-pk")
        )
        status_filter = self.request.query_params.get("status")
        if status_filter in PaymentOrder.Status.values:
            queryset = queryset.filter(status=status_filter)
        return queryset
