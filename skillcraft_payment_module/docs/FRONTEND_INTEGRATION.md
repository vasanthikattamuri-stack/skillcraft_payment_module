# Frontend Integration Guide — SkillCraft.AI Payment Module

> **For:** Frontend Developer  
> **Module:** Razorpay Payment Gateway  
> **Backend Base URL:** `http://127.0.0.1:8000` (dev) / `https://your-production-domain.com` (prod)

---

## Overview

This guide explains how to integrate the Razorpay Checkout from your frontend (React, Vue, plain HTML/JS, etc.) with the SkillCraft.AI payment backend.

**You are responsible for:** Calling the APIs and showing the Razorpay popup.  
**The backend is responsible for:** Price validation, order creation, payment verification, enrollment activation.

> 🔒 **Security note:** Never hardcode or calculate the payment amount in the frontend. Always use the `amount` returned by the Create Order API.

---

## Payment Flow Overview

```
Frontend                              Backend                        Razorpay
   │                                     │                              │
   │── POST /api/payments/create-order/ ─▶│                              │
   │                                     │── create order API call ────▶│
   │                                     │◀── order_id, amount ─────────│
   │◀── order_id, key_id, amount ────────│                              │
   │                                     │                              │
   │── Open Razorpay Checkout popup ─────────────────────────────────▶ │
   │                                     │                              │
   │◀─── payment_id, signature ──────────────────────────────────────── │
   │                                     │                              │
   │── POST /api/payments/verify/ ───────▶│                              │
   │                                     │── verify & fetch payment ───▶│
   │                                     │◀── payment status ───────────│
   │◀── success/failure response ────────│                              │
```

---

## Step 1 — Include the Razorpay Checkout Script

Add this to your HTML `<head>`:

```html
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
```

---

## Step 2 — Get a JWT Token (Authentication)

Before calling any payment API, the student must be logged in and you must have a JWT access token. Store it securely (memory or `httpOnly` cookie — not `localStorage`).

```javascript
// Example login call
async function login(username, password) {
    const response = await fetch('/api/token/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
    const data = await response.json();
    return data.access; // JWT access token
}
```

---

## Step 3 — Call Create Order API

When the student clicks "Buy Now":

```javascript
async function createOrder(purchaseType, courseId, accessToken) {
    const body = { purchase_type: purchaseType };
    if (purchaseType === 'course') {
        body.course_id = String(courseId); // Always send as string
    }

    const response = await fetch('/api/payments/create-order/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${accessToken}`
        },
        body: JSON.stringify(body)
    });

    const data = await response.json();

    if (!data.success) {
        // Show error to student
        console.error('Order creation failed:', data.message);
        return null;
    }

    return data.data; // Contains razorpay_order_id, amount, razorpay_key_id
}
```

---

## Step 4 — Open Razorpay Checkout

Use the `amount`, `razorpay_order_id`, and `razorpay_key_id` from Step 3:

```javascript
function openRazorpayCheckout(orderData, studentName, studentEmail, onSuccess, onFailure) {
    const options = {
        key: orderData.razorpay_key_id,     // Public key — safe to use in frontend
        amount: orderData.amount,            // In paise — backend already calculated this
        currency: orderData.currency,        // "INR"
        order_id: orderData.razorpay_order_id,
        name: 'SkillCraft.AI',
        description: orderData.course_title || 'Complete Combo Package',
        image: '/static/logo.png',           // Optional: your logo URL

        // Prefill student details
        prefill: {
            name: studentName,
            email: studentEmail
        },

        // Called when payment succeeds in Razorpay Checkout
        handler: function(response) {
            // response contains:
            // - response.razorpay_payment_id
            // - response.razorpay_order_id
            // - response.razorpay_signature
            onSuccess(response);
        },

        // Theme (optional)
        theme: { color: '#6366f1' },

        // Called when student closes the popup without paying
        modal: {
            ondismiss: function() {
                console.log('Payment popup closed by student.');
                onFailure('dismissed');
            }
        }
    };

    const rzp = new Razorpay(options);

    // Handle payment failures (e.g. card declined)
    rzp.on('payment.failed', function(response) {
        console.error('Payment failed:', response.error.description);
        onFailure(response.error.description);
    });

    rzp.open();
}
```

---

## Step 5 — Verify Payment with Backend

> ⚠️ **Never skip this step.** The Razorpay checkout `handler` callback does NOT mean the money was captured. You MUST call the verify API.

```javascript
async function verifyPayment(razorpayResponse, accessToken) {
    const response = await fetch('/api/payments/verify/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${accessToken}`
        },
        body: JSON.stringify({
            razorpay_order_id: razorpayResponse.razorpay_order_id,
            razorpay_payment_id: razorpayResponse.razorpay_payment_id,
            razorpay_signature: razorpayResponse.razorpay_signature
        })
    });

    return await response.json();
}
```

---

## Step 6 — Display Success or Failure

```javascript
async function handleVerifyResponse(verifyData) {
    if (verifyData.success && verifyData.data.order_status === 'paid') {
        // ✅ Payment captured — enrollment activated
        showSuccessMessage('Payment successful! Your course access has been activated.');
        redirectToCourses();

    } else if (verifyData.data?.order_status === 'pending') {
        // ⏳ Authorized but not captured yet
        showInfoMessage(
            'Payment authorized. Access will be activated shortly. ' +
            'You can check your payment status in your dashboard.'
        );

    } else {
        // ❌ Payment failed
        showErrorMessage(verifyData.message || 'Payment failed. Please try again.');
    }
}
```

---

## Step 7 — Check Payment Status (Optional Polling)

For the "pending" case (authorized but not captured), you can poll the status API:

```javascript
async function pollPaymentStatus(razorpayOrderId, accessToken, maxAttempts = 10) {
    for (let i = 0; i < maxAttempts; i++) {
        await new Promise(resolve => setTimeout(resolve, 3000)); // Wait 3 seconds

        const response = await fetch(`/api/payments/status/${razorpayOrderId}/`, {
            headers: { 'Authorization': `Bearer ${accessToken}` }
        });
        const data = await response.json();

        if (data.data?.order_status === 'paid') {
            showSuccessMessage('Payment confirmed! Enrollment activated.');
            return 'paid';
        }

        if (data.data?.order_status === 'failed') {
            showErrorMessage('Payment was not completed. Please try again.');
            return 'failed';
        }
    }
    return 'timeout';
}
```

---

## Complete Working Example

This is a complete, self-contained HTML page you can use as a reference:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SkillCraft.AI — Buy Course</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        button { background: #6366f1; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .message { margin-top: 20px; padding: 12px; border-radius: 6px; }
        .success { background: #d1fae5; color: #065f46; }
        .error { background: #fee2e2; color: #991b1b; }
        .info { background: #dbeafe; color: #1e40af; }
    </style>
</head>
<body>
    <h1>SkillCraft.AI — Purchase</h1>

    <div>
        <p><strong>Individual Course (ID: 12)</strong> — ₹5,000</p>
        <button id="buy-course-btn" onclick="startPayment('course', '12')">
            Buy Course — ₹5,000
        </button>
    </div>

    <br>

    <div>
        <p><strong>Complete Combo Package</strong> — ₹20,000</p>
        <button id="buy-combo-btn" onclick="startPayment('combo', null)">
            Buy Combo — ₹20,000
        </button>
    </div>

    <div id="message" class="message" style="display:none;"></div>

    <script>
        // ─────────────────────────────────────────────
        // Configuration
        // ─────────────────────────────────────────────
        const API_BASE = 'http://127.0.0.1:8000';

        // In a real app, get this from your auth system (login session/cookie).
        // For testing, paste your JWT access token here.
        const ACCESS_TOKEN = 'YOUR_JWT_ACCESS_TOKEN_HERE';

        const STUDENT_NAME = 'Test Student';
        const STUDENT_EMAIL = 'student@example.com';

        // ─────────────────────────────────────────────
        // UI helpers
        // ─────────────────────────────────────────────
        function showMessage(text, type) {
            const el = document.getElementById('message');
            el.textContent = text;
            el.className = `message ${type}`;
            el.style.display = 'block';
        }

        function setButtonsDisabled(disabled) {
            document.getElementById('buy-course-btn').disabled = disabled;
            document.getElementById('buy-combo-btn').disabled = disabled;
        }

        // ─────────────────────────────────────────────
        // Main payment flow
        // ─────────────────────────────────────────────
        async function startPayment(purchaseType, courseId) {
            setButtonsDisabled(true);
            showMessage('Creating order...', 'info');

            try {
                // STEP 1: Create order on backend
                const orderBody = { purchase_type: purchaseType };
                if (courseId) orderBody.course_id = String(courseId);

                const orderRes = await fetch(`${API_BASE}/api/payments/create-order/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${ACCESS_TOKEN}`
                    },
                    body: JSON.stringify(orderBody)
                });
                const orderData = await orderRes.json();

                if (!orderData.success) {
                    showMessage(orderData.message || 'Failed to create order.', 'error');
                    setButtonsDisabled(false);
                    return;
                }

                const { razorpay_order_id, amount, currency, razorpay_key_id, course_title } = orderData.data;

                // STEP 2: Open Razorpay Checkout
                showMessage('Opening payment popup...', 'info');

                const rzpOptions = {
                    key: razorpay_key_id,
                    amount: amount,
                    currency: currency,
                    order_id: razorpay_order_id,
                    name: 'SkillCraft.AI',
                    description: course_title,
                    prefill: { name: STUDENT_NAME, email: STUDENT_EMAIL },
                    theme: { color: '#6366f1' },

                    handler: async function(rzpResponse) {
                        // STEP 3: Verify payment on backend
                        showMessage('Verifying payment...', 'info');

                        const verifyRes = await fetch(`${API_BASE}/api/payments/verify/`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `Bearer ${ACCESS_TOKEN}`
                            },
                            body: JSON.stringify({
                                razorpay_order_id: rzpResponse.razorpay_order_id,
                                razorpay_payment_id: rzpResponse.razorpay_payment_id,
                                razorpay_signature: rzpResponse.razorpay_signature
                            })
                        });
                        const verifyData = await verifyRes.json();

                        // STEP 4: Show result
                        if (verifyData.success && verifyData.data?.order_status === 'paid') {
                            showMessage(
                                '✅ Payment successful! Your course access has been activated. ' +
                                `Payment ID: ${verifyData.data.razorpay_payment_id}`,
                                'success'
                            );
                        } else if (verifyData.data?.order_status === 'pending') {
                            showMessage(
                                '⏳ Payment authorized. Enrollment will be activated shortly. ' +
                                'Check your dashboard for status.',
                                'info'
                            );
                        } else {
                            showMessage(
                                '❌ ' + (verifyData.message || 'Payment verification failed.'),
                                'error'
                            );
                        }
                        setButtonsDisabled(false);
                    },

                    modal: {
                        ondismiss: function() {
                            showMessage('Payment cancelled.', 'info');
                            setButtonsDisabled(false);
                        }
                    }
                };

                const rzp = new Razorpay(rzpOptions);
                rzp.on('payment.failed', function(response) {
                    showMessage('❌ Payment failed: ' + response.error.description, 'error');
                    setButtonsDisabled(false);
                });
                rzp.open();

            } catch (err) {
                console.error(err);
                showMessage('An unexpected error occurred. Please try again.', 'error');
                setButtonsDisabled(false);
            }
        }
    </script>
</body>
</html>
```

---

## Payment History Page

To show a student their purchase history:

```javascript
async function fetchPaymentHistory(accessToken, page = 1, pageSize = 10) {
    const response = await fetch(
        `/api/payments/history/?page=${page}&page_size=${pageSize}`,
        { headers: { 'Authorization': `Bearer ${accessToken}` } }
    );
    const data = await response.json();

    if (!data.success) return null;

    // data.data.results = array of orders
    // data.data.count = total orders
    // data.data.total_pages = total pages
    return data.data;
}
```

---

## Important Notes

1. **Never send `amount` from the frontend.** The backend ignores it and uses the backend-defined price.
2. **Always call `/api/payments/verify/`** after the Razorpay `handler` callback. The handler fires even for authorized (not captured) payments.
3. **Store the `razorpay_order_id`** so you can check status later.
4. **Handle the `202 Accepted` response** from verify — it means payment is authorized but not yet captured. The student is NOT yet enrolled.
5. **Test with Razorpay Test Cards** — visit https://razorpay.com/docs/payments/payments/test-card-upi-details/ for test card numbers.
