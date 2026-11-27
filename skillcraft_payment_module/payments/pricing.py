"""
Backend-controlled pricing.

The frontend NEVER sends the price. The amount charged is always computed
here from the purchase type.

| Purchase type | Price (INR) | Amount sent to Razorpay (paise) |
|---------------|-------------|---------------------------------|
| course        | 5,000       | 500000                          |
| combo         | 20,000      | 2000000                         |
"""
from decimal import ROUND_HALF_UP, Decimal

from .models import PurchaseType

# Prices in Indian Rupees. Decimal is used (not float) to avoid rounding bugs.
PRICES_INR = {
    PurchaseType.COURSE: Decimal("5000.00"),
    PurchaseType.COMBO: Decimal("20000.00"),
}


def inr_to_paise(amount_inr):
    """
    Convert rupees to paise (1 INR = 100 paise). Razorpay expects amounts in
    the smallest currency unit, as an integer.

    >>> inr_to_paise(Decimal("5000"))
    500000
    """
    amount = Decimal(str(amount_inr))
    paise = amount * 100
    if paise != paise.to_integral_value():
        raise ValueError("Amount has more than 2 decimal places.")
    if paise <= 0:
        raise ValueError("Amount must be greater than zero.")
    return int(paise)


def paise_to_inr(amount_paise):
    """Convert paise to a rupee Decimal with 2 decimal places (for display)."""
    return (Decimal(amount_paise) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_price_inr(purchase_type):
    """Return the official price in INR for a purchase type."""
    try:
        return PRICES_INR[purchase_type]
    except KeyError:
        raise ValueError(f"Unknown purchase type: {purchase_type!r}") from None


def get_price_paise(purchase_type):
    """Return the official price in paise for a purchase type."""
    return inr_to_paise(get_price_inr(purchase_type))
