"""
Serializers = input validation + output formatting.

Note: CreateOrderSerializer has NO amount/price field. If a client sends
"amount", DRF simply ignores it - the backend always decides the price.
"""
from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import PaymentOrder, PurchaseType
from .pricing import paise_to_inr


class CreateOrderSerializer(serializers.Serializer):
    purchase_type = serializers.ChoiceField(
        choices=PurchaseType.choices,
        error_messages={"invalid_choice": "Invalid purchase_type. Allowed values: course, combo."},
    )
    # Accepts 12 or "12" (or a slug/UUID string in the real LMS).
    course_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=64, trim_whitespace=True
    )

    def validate(self, attrs):
        purchase_type = attrs["purchase_type"]
        course_id = (attrs.get("course_id") or "").strip()

        if purchase_type == PurchaseType.COURSE and not course_id:
            raise serializers.ValidationError(
                {"course_id": ["course_id is required when purchase_type is 'course'."]}
            )
        if purchase_type == PurchaseType.COMBO and course_id:
            raise serializers.ValidationError(
                {"course_id": ["course_id must not be sent when purchase_type is 'combo'."]}
            )
        attrs["course_id"] = course_id
        return attrs


class VerifyPaymentSerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField(
        max_length=64,
        validators=[RegexValidator(r"^order_[A-Za-z0-9]+$", "Invalid razorpay_order_id format.")],
    )
    razorpay_payment_id = serializers.CharField(
        max_length=64,
        validators=[RegexValidator(r"^pay_[A-Za-z0-9]+$", "Invalid razorpay_payment_id format.")],
    )
    razorpay_signature = serializers.CharField(
        max_length=128,
        validators=[RegexValidator(r"^[a-fA-F0-9]{64}$", "Invalid razorpay_signature format.")],
    )


class _OrderOutputMixin(serializers.Serializer):
    """Shared read-only fields computed from the order's primary payment."""

    amount_inr = serializers.SerializerMethodField()
    order_status = serializers.CharField(source="status", read_only=True)
    payment_status = serializers.SerializerMethodField()
    razorpay_payment_id = serializers.SerializerMethodField()

    def _payment(self, obj):
        cache = self.context.setdefault("_primary_payment_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = obj.primary_payment()
        return cache[obj.pk]

    def get_amount_inr(self, obj):
        return str(paise_to_inr(obj.amount))

    def get_payment_status(self, obj):
        payment = self._payment(obj)
        return payment.status if payment else None

    def get_razorpay_payment_id(self, obj):
        payment = self._payment(obj)
        return payment.razorpay_payment_id if payment else None


class PaymentStatusSerializer(_OrderOutputMixin, serializers.ModelSerializer):
    """API 4 output. Contains no secrets and no other users' data."""

    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = [
            "internal_order_id",
            "razorpay_order_id",
            "purchase_type",
            "course_id",
            "course_title",
            "amount",
            "amount_inr",
            "currency",
            "order_status",
            "payment_status",
            "razorpay_payment_id",
            "payment_method",
            "enrollment_activated",
            "paid_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_payment_method(self, obj):
        payment = self._payment(obj)
        return (payment.method or None) if payment else None


class PaymentHistorySerializer(_OrderOutputMixin, serializers.ModelSerializer):
    """API 5 output (one row per order)."""

    date = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = PaymentOrder
        fields = [
            "internal_order_id",
            "razorpay_order_id",
            "purchase_type",
            "course_id",
            "course_title",
            "amount",
            "amount_inr",
            "currency",
            "order_status",
            "payment_status",
            "razorpay_payment_id",
            "date",
            "paid_at",
        ]
        read_only_fields = fields
