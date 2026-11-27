"""
Permissions for the payments API.

All student-facing endpoints require an authenticated user. Which
authentication method is used (JWT, Token, Session ...) is decided by the
project's REST_FRAMEWORK settings - the payments app does not force one.

The webhook endpoint is the only public endpoint; it is protected by the
Razorpay webhook signature instead of user authentication.
"""
from rest_framework.permissions import BasePermission


class IsOrderOwner(BasePermission):
    """Object-level check: the PaymentOrder / Payment must belong to the user."""

    message = "You do not have access to this order."

    def has_object_permission(self, request, view, obj):
        owner_id = getattr(obj, "user_id", None)
        if owner_id is None and hasattr(obj, "order"):
            owner_id = obj.order.user_id
        return owner_id is not None and owner_id == request.user.pk
