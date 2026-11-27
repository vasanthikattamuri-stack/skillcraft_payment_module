"""
URL routes for the payments module.

Include in the project's urls.py:
    path("api/payments/", include("payments.urls")),
"""
from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("create-order/", views.CreateOrderView.as_view(), name="create-order"),
    path("verify/", views.VerifyPaymentView.as_view(), name="verify"),
    path("webhook/", views.RazorpayWebhookView.as_view(), name="webhook"),
    path("status/<str:razorpay_order_id>/", views.PaymentStatusView.as_view(), name="status"),
    path("history/", views.PaymentHistoryView.as_view(), name="history"),
]
