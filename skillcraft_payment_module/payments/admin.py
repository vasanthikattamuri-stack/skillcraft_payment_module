"""
Django admin for payment records.

Financial records are READ-ONLY in the admin: statuses must only change
through verified Razorpay data (Verify API / webhooks), never by hand.
"""
from django.contrib import admin

from .models import Payment, PaymentOrder, WebhookEvent


class ReadOnlyAdminMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("razorpay_payment_id", "status", "amount", "currency", "method", "paid_at", "created_at")
    readonly_fields = fields


@admin.register(PaymentOrder)
class PaymentOrderAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "internal_order_id", "razorpay_order_id", "user", "purchase_type",
        "course_id", "amount", "currency", "status", "enrollment_activated", "created_at",
    )
    list_filter = ("status", "purchase_type", "enrollment_activated", "created_at")
    search_fields = ("internal_order_id", "razorpay_order_id", "course_id")
    readonly_fields = [f.name for f in PaymentOrder._meta.fields]
    inlines = [PaymentInline]
    date_hierarchy = "created_at"


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("razorpay_payment_id", "order", "status", "amount", "currency", "method", "paid_at", "created_at")
    list_filter = ("status", "method", "created_at")
    search_fields = ("razorpay_payment_id", "order__internal_order_id", "order__razorpay_order_id")
    readonly_fields = [f.name for f in Payment._meta.fields]


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("event_id", "event_type", "status", "razorpay_order_id", "attempts", "received_at", "processed_at")
    list_filter = ("status", "event_type", "received_at")
    search_fields = ("event_id", "razorpay_order_id", "razorpay_payment_id")
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
