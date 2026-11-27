# API Documentation — SkillCraft.AI Payment Module

> **Base URL:** `http://127.0.0.1:8000`  
> **Authentication:** JWT Bearer Token in `Authorization` header  
> **Response Envelope:** Every response uses `{"success": bool, "message": "...", "data": {...}, "errors": {...}}`

---

## Table of Contents
1. [API 1 — Create Razorpay Order](#api-1--create-razorpay-order)
2. [API 2 — Verify Payment](#api-2--verify-payment)
3. [API 3 — Razorpay Webhook](#api-3--razorpay-webhook)
4. [API 4 — Payment Status](#api-4--payment-status)
5. [API 5 — Payment History](#api-5--payment-history)
6. [Error Codes Reference](#error-codes-reference)

---

## API 1 — Create Razorpay Order

**Method:** `POST`  
**URL:** `/api/payments/create-order/`  
**Authentication:** Required — JWT Bearer token  
**Purpose:** Create a Razorpay order when a student selects a course or combo package.

> ⚠️ **Important:** The price is set entirely by the backend. Never send `amount` from the frontend — it will be ignored. The backend always charges ₹5,000 for a course and ₹20,000 for the combo.

### Request — Individual Course

```json
{
    "purchase_type": "course",
    "course_id": "12"
}
```

### Request — Combo Package

```json
{
    "purchase_type": "combo"
}
```

### Request Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `purchase_type` | string | ✅ | Must be `"course"` or `"combo"` |
| `course_id` | string | ✅ for course | ID of the course to purchase. Demo IDs: 11, 12, 13, 14, 15 |

### Success Response — 201 Created

```json
{
    "success": true,
    "message": "Order created successfully",
    "data": {
        "internal_order_id": "SCO20261127A1B2C3D4E5",
        "razorpay_order_id": "order_P1q2r3s4t5u6v7",
        "amount": 500000,
        "amount_inr": "5000.00",
        "currency": "INR",
        "purchase_type": "course",
        "course_id": "12",
        "course_title": "DEMO Course 12",
        "razorpay_key_id": "rzp_test_XXXXXXXXXXXXXX",
        "reused_existing_order": false
    }
}
```

> **Note:** `razorpay_key_id` is the **public** key — safe to send to the frontend. The secret key is never included.

### Success Response — 200 OK (Order Reused)

If the student clicks "Pay" twice within 30 minutes for the same unpaid order, the existing order is returned instead of creating a duplicate.

```json
{
    "success": true,
    "message": "Existing unpaid order returned",
    "data": {
        "reused_existing_order": true,
        ...
    }
}
```

### Error Responses

| Status | Reason | Response |
|---|---|---|
| 400 | Missing `course_id` for course purchase | `{"errors": {"course_id": ["course_id is required..."]}}` |
| 400 | Invalid/unknown `course_id` | `{"errors": {"course_id": ["Invalid or unavailable course."]}}` |
| 400 | Invalid `purchase_type` | `{"errors": {"purchase_type": ["Invalid purchase_type..."]}}` |
| 401 | No auth token | `{"message": "Authentication credentials were not provided."}` |
| 409 | Already purchased | `{"message": "You already have access to this purchase."}` |
| 503 | Combo not configured | `{"message": "The combo package is not available right now."}` |
| 502 | Razorpay unavailable | `{"message": "Payment gateway is temporarily unavailable."}` |

### Validation Rules
- `purchase_type` must be exactly `"course"` or `"combo"`.
- `course_id` is required when `purchase_type` is `"course"`.
- `course_id` must NOT be sent when `purchase_type` is `"combo"`.
- `course_id` must be a valid course identifier (checked against the demo catalog or real LMS).
- Amount is NEVER accepted from the client — it is always determined server-side.

---

## API 2 — Verify Payment

**Method:** `POST`  
**URL:** `/api/payments/verify/`  
**Authentication:** Required — JWT Bearer token  
**Purpose:** After the student completes payment in the Razorpay Checkout popup, the frontend sends these three values to verify the payment.

> ⚠️ **Important:** A valid checkout signature alone is NOT proof of payment capture. This API fetches the actual payment status from Razorpay and only grants access after confirming `status = "captured"`.

### Request

```json
{
    "razorpay_order_id": "order_P1q2r3s4t5u6v7",
    "razorpay_payment_id": "pay_XXXXXXXXXXXXXXXXX",
    "razorpay_signature": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
}
```

### Request Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `razorpay_order_id` | string | ✅ | Must match `order_XXXXX` format |
| `razorpay_payment_id` | string | ✅ | Must match `pay_XXXXX` format |
| `razorpay_signature` | string | ✅ | 64-character hex HMAC-SHA256 signature |

### Success Response — 200 OK (Captured)

```json
{
    "success": true,
    "message": "Payment verified successfully",
    "data": {
        "internal_order_id": "SCO20261127A1B2C3D4E5",
        "razorpay_order_id": "order_P1q2r3s4t5u6v7",
        "purchase_type": "course",
        "course_id": "12",
        "course_title": "DEMO Course 12",
        "amount": 500000,
        "amount_inr": "5000.00",
        "currency": "INR",
        "order_status": "paid",
        "payment_status": "captured",
        "razorpay_payment_id": "pay_XXXXXXXXXXXXXXXXX",
        "payment_method": "upi",
        "enrollment_activated": true,
        "paid_at": "2026-11-27T08:30:00Z",
        "created_at": "2026-11-27T08:25:00Z",
        "updated_at": "2026-11-27T08:30:00Z"
    }
}
```

### Response — 202 Accepted (Authorized, Not Yet Captured)

The payment was authorized but not captured yet. The student has NOT yet been enrolled. Access will be activated automatically when the `payment.captured` webhook arrives.

```json
{
    "success": true,
    "message": "Payment is authorized but not yet captured. Access will be activated automatically once the payment is captured.",
    "data": {
        "order_status": "pending",
        "payment_status": "authorized",
        "enrollment_activated": false
    }
}
```

### Error Responses

| Status | Reason |
|---|---|
| 400 | Invalid/tampered signature |
| 400 | Amount or currency mismatch between payment and order |
| 400 | Payment failed |
| 404 | Order not found (or belongs to another user) |
| 502 | Cannot reach Razorpay API |

---

## API 3 — Razorpay Webhook

**Method:** `POST`  
**URL:** `/api/payments/webhook/`  
**Authentication:** None (Razorpay server-to-server call)  
**Security:** Webhook signature in `X-Razorpay-Signature` header + `X-Razorpay-Event-Id` for idempotency

> ⚠️ **Never confuse** the checkout signature and the webhook signature. The webhook uses `RAZORPAY_WEBHOOK_SECRET`, not `RAZORPAY_KEY_SECRET`.

### Events Handled

| Event | Action |
|---|---|
| `payment.captured` | Marks order PAID, creates/updates Payment, activates enrollment |
| `payment.failed` | Marks order FAILED, records failure |
| `order.paid` | Confirms order PAID (supplementary — same as `payment.captured`) |

### Webhook Payload Structure

Razorpay sends this JSON body:

```json
{
    "entity": "event",
    "account_id": "acc_YourAccountID",
    "event": "payment.captured",
    "contains": ["payment"],
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_XXXXXXXXXXXXXXXXX",
                "entity": "payment",
                "amount": 500000,
                "currency": "INR",
                "status": "captured",
                "order_id": "order_P1q2r3s4t5u6v7",
                "method": "upi",
                "captured": true
            }
        }
    },
    "created_at": 1700000000
}
```

### Required Headers

| Header | Description |
|---|---|
| `X-Razorpay-Signature` | HMAC-SHA256 of raw body bytes with `RAZORPAY_WEBHOOK_SECRET` |
| `X-Razorpay-Event-Id` | Unique event ID from Razorpay (used for idempotency) |

### Success Response — 200 OK

```json
{
    "success": true,
    "message": "Payment captured.",
    "data": {"event_status": "processed"}
}
```

### Idempotency

If the same `X-Razorpay-Event-Id` is received twice, the second delivery is acknowledged (200) but NOT reprocessed:

```json
{
    "success": true,
    "message": "Duplicate event - already processed.",
    "data": {"event_status": "duplicate"}
}
```

### Error Responses

| Status | Reason |
|---|---|
| 400 | Missing or invalid `X-Razorpay-Signature` |
| 400 | Invalid JSON body |

### Local Webhook Testing

1. Install ngrok: `choco install ngrok` or download from https://ngrok.com
2. Start your server: `python manage.py runserver`
3. In another terminal: `ngrok http 8000`
4. Copy the HTTPS URL (e.g. `https://abc123.ngrok.io`)
5. In Razorpay Dashboard → Settings → Webhooks:
   - URL: `https://abc123.ngrok.io/api/payments/webhook/`
   - Secret: your `RAZORPAY_WEBHOOK_SECRET`
   - Events: check `payment.captured`, `payment.failed`, `order.paid`

---

## API 4 — Payment Status

**Method:** `GET`  
**URL:** `/api/payments/status/{razorpay_order_id}/`  
**Authentication:** Required — JWT Bearer token  
**Purpose:** Let a student check the current status of a specific order.

**Example:** `GET /api/payments/status/order_P1q2r3s4t5u6v7/`

### Success Response — 200 OK

```json
{
    "success": true,
    "message": "Payment status fetched successfully",
    "data": {
        "internal_order_id": "SCO20261127A1B2C3D4E5",
        "razorpay_order_id": "order_P1q2r3s4t5u6v7",
        "purchase_type": "course",
        "course_id": "12",
        "course_title": "DEMO Course 12",
        "amount": 500000,
        "amount_inr": "5000.00",
        "currency": "INR",
        "order_status": "paid",
        "payment_status": "captured",
        "razorpay_payment_id": "pay_XXXXXXXXXXXXXXXXX",
        "payment_method": "upi",
        "enrollment_activated": true,
        "paid_at": "2026-11-27T08:30:00Z",
        "created_at": "2026-11-27T08:25:00Z",
        "updated_at": "2026-11-27T08:30:00Z"
    }
}
```

### Order Status Values

| `order_status` | Meaning |
|---|---|
| `created` | Order created, no payment attempted yet |
| `pending` | Payment authorized but not captured |
| `paid` | Payment captured — student has access |
| `failed` | Last payment attempt failed |

### Error Responses

| Status | Reason |
|---|---|
| 404 | Order not found (or belongs to another user — 404 is used intentionally to prevent order ID discovery) |
| 401/403 | Not authenticated |

---

## API 5 — Payment History

**Method:** `GET`  
**URL:** `/api/payments/history/`  
**Authentication:** Required — JWT Bearer token  
**Purpose:** Return the authenticated student's payment history.

### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | integer | 1 | Page number |
| `page_size` | integer | 10 | Results per page (max 50) |
| `status` | string | (all) | Filter by order status: `created`, `pending`, `paid`, `failed` |

**Example:** `GET /api/payments/history/?page=1&page_size=5&status=paid`

### Success Response — 200 OK

```json
{
    "success": true,
    "message": "Payment history fetched successfully",
    "data": {
        "count": 2,
        "total_pages": 1,
        "current_page": 1,
        "next": null,
        "previous": null,
        "results": [
            {
                "internal_order_id": "SCO20261127F6G7H8I9J0",
                "razorpay_order_id": "order_ComboXXXXXXX",
                "purchase_type": "combo",
                "course_id": "",
                "course_title": "Complete Combo Package",
                "amount": 2000000,
                "amount_inr": "20000.00",
                "currency": "INR",
                "order_status": "paid",
                "payment_status": "captured",
                "razorpay_payment_id": "pay_YYYYYYYYYYYYYYYYY",
                "date": "2026-11-27T09:00:00Z",
                "paid_at": "2026-11-27T09:05:00Z"
            },
            {
                "internal_order_id": "SCO20261127A1B2C3D4E5",
                "razorpay_order_id": "order_P1q2r3s4t5u6v7",
                "purchase_type": "course",
                "course_id": "12",
                "course_title": "DEMO Course 12",
                "amount": 500000,
                "amount_inr": "5000.00",
                "currency": "INR",
                "order_status": "paid",
                "payment_status": "captured",
                "razorpay_payment_id": "pay_XXXXXXXXXXXXXXXXX",
                "date": "2026-11-27T08:25:00Z",
                "paid_at": "2026-11-27T08:30:00Z"
            }
        ]
    }
}
```

---

## Error Codes Reference

### HTTP Status Codes Used

| Code | Meaning |
|---|---|
| 200 | Success |
| 201 | Order created successfully |
| 202 | Accepted but pending (authorized payment) |
| 400 | Bad request / validation error / signature failure |
| 401 | Not authenticated |
| 403 | Forbidden (authenticated but no permission) |
| 404 | Resource not found (or ownership check failed) |
| 409 | Conflict (already purchased, duplicate payment) |
| 502 | Payment gateway (Razorpay) error |
| 503 | Service unavailable (misconfiguration) |

### Payment Status Values

| Value | Meaning |
|---|---|
| `created` | Payment object created |
| `authorized` | Card authorized but NOT captured |
| `captured` | Money received — enrollment activated |
| `failed` | Payment declined |
| `refunded` | Payment refunded |
