# SkillCraft.AI — Payment Module

> **Reusable Django payment module** for the SkillCraft.AI EdTech LMS.  
> Built by: Backend Team — Task 4: Razorpay Payment Gateway & Checkout API

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Features](#features)
3. [Technology Stack](#technology-stack)
4. [Project Structure](#project-structure)
5. [Installation](#installation)
6. [Environment Configuration](#environment-configuration)
7. [Running the Server](#running-the-server)
8. [Running Automated Tests](#running-automated-tests)
9. [Razorpay Test Mode Setup](#razorpay-test-mode-setup)
10. [API Quick Reference](#api-quick-reference)

---

## Project Overview

This is a **standalone demonstration project** for the SkillCraft.AI payment module.

The key directory is **`payments/`** — it is the **reusable Django app** that the team leader will copy into the main SkillCraft.AI project. Everything else (`config/`, `manage.py`, `.env.example`) is scaffolding for local testing only.

### What this module does
- Lets a student purchase an **Individual Course (₹5,000)** or the **Complete Combo Package (₹20,000)**.
- Creates a Razorpay order (backend-controlled price — the frontend never sets the amount).
- Verifies payment using **HMAC-SHA256 checkout signature** + a Razorpay API call to confirm capture.
- Handles **Razorpay webhooks** with idempotency and transaction safety.
- Activates LMS enrollment **only after a confirmed captured payment**.
- Provides Payment Status and Payment History APIs for the student.

---

## Features

| Feature | Detail |
|---|---|
| ✅ Razorpay Test Mode | No real money — safe for development |
| ✅ Backend-controlled pricing | Frontend cannot manipulate the amount |
| ✅ Checkout signature verification | HMAC-SHA256 with `RAZORPAY_KEY_SECRET` |
| ✅ Webhook signature verification | HMAC-SHA256 with `RAZORPAY_WEBHOOK_SECRET` (separate key!) |
| ✅ Webhook idempotency | Same event delivered twice → processed only once |
| ✅ Duplicate payment prevention | `unique` DB constraint on `razorpay_payment_id` |
| ✅ Authorized vs. Captured | Authorized payment ≠ captured; enrollment only on capture |
| ✅ Database transactions | `select_for_update()` prevents race conditions |
| ✅ Enrollment adapter pattern | Payments app never imports LMS models directly |
| ✅ JWT + Session authentication | Works with Postman Bearer tokens and browser sessions |
| ✅ Retry command | `python manage.py retry_enrollments` for failed enrollments |
| ✅ 61 automated tests | 100% pass, no real Razorpay credentials needed |
| ✅ Read-only admin | Financial records cannot be edited from the admin |

---

## Technology Stack

| Component | Library / Version |
|---|---|
| Language | Python 3.10 |
| Web Framework | Django 5.2 |
| REST API | Django REST Framework 3.18 |
| Payment Gateway | Razorpay Python SDK 2.0.1 |
| Authentication | djangorestframework-simplejwt 5.5 |
| Environment Variables | python-dotenv 1.2 |
| Database (demo) | SQLite (zero setup) |
| Database (production) | PostgreSQL (compatible) |
| Signature Algorithm | HMAC-SHA256 |

---

## Project Structure

```
skillcraft_payment_module/
│
├── manage.py                      # Django management script
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── .env.example                   # Environment variable template
├── .gitignore
│
├── config/                        # Demo project configuration (not copied to main LMS)
│   ├── settings.py                # Settings (loads from .env)
│   ├── urls.py                    # Routes /api/payments/ to payments app
│   ├── wsgi.py
│   └── asgi.py
│
├── payments/                      ← THE REUSABLE APP (copy this to the main project)
│   ├── models.py                  # PaymentOrder, Payment, WebhookEvent
│   ├── views.py                   # 5 API views
│   ├── serializers.py             # Request validation + response formatting
│   ├── services.py                # Business logic (create, verify, webhook, enrollment)
│   ├── signatures.py              # HMAC-SHA256 checkout & webhook verification
│   ├── gateway.py                 # Razorpay SDK wrapper
│   ├── pricing.py                 # Backend price table (₹5,000 / ₹20,000)
│   ├── conf.py                    # Reads settings at call-time (override_settings friendly)
│   ├── exceptions.py              # Domain exceptions with HTTP status codes
│   ├── permissions.py             # IsOrderOwner permission
│   ├── pagination.py              # PaymentHistoryPagination
│   ├── compat.py                  # Django 4.2 / 5.x CheckConstraint compat
│   ├── urls.py                    # 5 URL patterns
│   ├── apps.py
│   ├── admin.py                   # Read-only admin for all 3 models
│   │
│   ├── adapters/                  # LMS integration adapters
│   │   ├── base.py                # BaseCourseCatalogAdapter, BaseEnrollmentAdapter
│   │   ├── demo.py                # Demo implementations (no real LMS models)
│   │   └── __init__.py            # get_course_catalog(), get_enrollment_adapter()
│   │
│   ├── management/commands/
│   │   └── retry_enrollments.py   # Retry failed enrollment activations
│   │
│   ├── migrations/
│   │   └── 0001_initial.py        # Initial migration
│   │
│   └── tests/
│       ├── utils.py               # Base test case, mock gateway, mock adapters
│       ├── test_create_order.py   # API 1 tests (15 test cases)
│       ├── test_verify.py         # API 2 tests (15 test cases)
│       ├── test_webhook.py        # API 3 tests (13 test cases)
│       ├── test_status.py         # API 4 tests (8 test cases)
│       └── test_history.py        # API 5 tests (7 test cases)
│
├── docs/
│   ├── API_DOCUMENTATION.md       # Full API reference
│   ├── FRONTEND_INTEGRATION.md    # Guide for the frontend developer
│   └── MAIN_PROJECT_INTEGRATION.md # Guide for the team leader
│
└── postman/
    └── SkillCraft_Payment_API.postman_collection.json
```

---

## Installation

### Prerequisites
- Python 3.10 or later
- Git

### Step 1 — Clone the repository

```bash
git clone <repository-url>
cd skillcraft_payment_module
```

### Step 2 — Create and activate a virtual environment

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and fill in your values:

```env
DJANGO_SECRET_KEY=your-random-secret-key-here
DEBUG=True
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=your_razorpay_key_secret_here
RAZORPAY_WEBHOOK_SECRET=your_razorpay_webhook_secret_here
```

> **Tip:** To generate a secret key, run:  
> `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

### Step 5 — Run database migrations

```bash
python manage.py migrate
```

### Step 6 — Create a superuser (for Django Admin)

```bash
python manage.py createsuperuser
```

### Step 7 — Get a JWT access token for API testing

```bash
# Create a test user via Django shell
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.create_user(username='testuser', password='testpass123')
print('User created')
"
```

Then use Postman or curl to get a token:
```bash
curl -X POST http://127.0.0.1:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"testpass123"}'
```

> **Note:** The JWT token endpoints (`/api/token/` and `/api/token/refresh/`) need to be added to `config/urls.py`. See [API Quick Reference](#api-quick-reference) below.

**Add JWT endpoints to `config/urls.py`:**
```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/payments/", include("payments.urls")),
]
```

---

## Running the Server

```bash
python manage.py runserver
```

The server starts at: `http://127.0.0.1:8000`

Django Admin: `http://127.0.0.1:8000/admin/`

---

## Running Automated Tests

```bash
# Run all 61 tests
python manage.py test payments --verbosity 2
```

> No real Razorpay credentials are needed. All Razorpay API calls are mocked.

Expected output:
```
Found 61 test(s).
...
Ran 61 tests in X.XXXs
OK
```

**Run a specific test file:**
```bash
python manage.py test payments.tests.test_create_order --verbosity 2
python manage.py test payments.tests.test_verify --verbosity 2
python manage.py test payments.tests.test_webhook --verbosity 2
python manage.py test payments.tests.test_status --verbosity 2
python manage.py test payments.tests.test_history --verbosity 2
```

---

## Razorpay Test Mode Setup

1. Go to [https://dashboard.razorpay.com](https://dashboard.razorpay.com) and sign up for free.
2. Switch to **Test Mode** using the toggle at the top right.
3. Go to **Settings → API Keys** and click **Generate Test Key**.
4. Copy the **Key ID** and **Key Secret** into your `.env` file.
5. For webhook testing, go to **Settings → Webhooks** and add a webhook URL.
   - For local testing, use [ngrok](https://ngrok.com): `ngrok http 8000`
   - Your webhook URL will be: `https://your-ngrok-url.ngrok.io/api/payments/webhook/`
   - Select events: `payment.captured`, `payment.failed`, `order.paid`
   - Copy the **Webhook Secret** into `.env` as `RAZORPAY_WEBHOOK_SECRET`.

> **Test Cards:** Razorpay provides test card numbers at  
> https://razorpay.com/docs/payments/payments/test-card-upi-details/

---

## API Quick Reference

| # | Method | Endpoint | Auth | Purpose |
|---|---|---|---|---|
| 1 | POST | `/api/payments/create-order/` | JWT Bearer | Create Razorpay order |
| 2 | POST | `/api/payments/verify/` | JWT Bearer | Verify payment signature |
| 3 | POST | `/api/payments/webhook/` | None (signature) | Razorpay webhook receiver |
| 4 | GET | `/api/payments/status/{razorpay_order_id}/` | JWT Bearer | Check order status |
| 5 | GET | `/api/payments/history/` | JWT Bearer | Student payment history |

See `docs/API_DOCUMENTATION.md` for full request/response examples.

---

## Django System Check

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`
