"""
Domain exceptions raised by the payment services.

Each exception carries an HTTP status code and a SAFE, user-facing message.
Views turn them into JSON responses. Internal details (stack traces, Razorpay
raw errors, secrets) are logged on the server, never returned to clients.
"""
from rest_framework import status


class PaymentError(Exception):
    """Base class for all expected payment errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "Payment request could not be processed."

    def __init__(self, message=None, errors=None):
        self.message = message or self.default_message
        self.errors = errors or {}
        super().__init__(self.message)


class InvalidPurchaseError(PaymentError):
    """Purchase type / course id is invalid or not available."""

    default_message = "Invalid purchase request."


class ComboNotConfiguredError(PaymentError):
    """The combo course mapping is empty - the LMS has not supplied it."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The combo package is not available right now."


class AlreadyPurchasedError(PaymentError):
    status_code = status.HTTP_409_CONFLICT
    default_message = "You already have access to this purchase."


class OrderNotFoundError(PaymentError):
    # 404 is used both for "does not exist" and "belongs to another user",
    # so nobody can discover other students' order ids.
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "Order not found."


class SignatureVerificationFailed(PaymentError):
    default_message = "Payment signature verification failed."


class PaymentMismatchError(PaymentError):
    """Payment does not match the order (order id, amount or currency)."""

    default_message = "Payment details do not match the order."


class GatewayError(PaymentError):
    """Razorpay could not be reached or returned an unexpected error."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "Payment gateway is temporarily unavailable. Please try again."


class GatewayRequestRejected(GatewayError):
    """Razorpay rejected the request (e.g. unknown payment id)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The payment gateway rejected the request."
