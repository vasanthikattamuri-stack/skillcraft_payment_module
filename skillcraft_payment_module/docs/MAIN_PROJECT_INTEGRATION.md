# Main Project Integration Guide

> **For:** Team Leader / Main Project Developer  
> **Subject:** Integrating the `payments` app into the main SkillCraft.AI Django project

---

## Overview

This document explains how to copy the `payments` app from this standalone demo project into the **main SkillCraft.AI Django project**.

> **Important:** Only the `payments/` directory needs to be copied. The `config/` directory, `manage.py`, and `.env.example` are for the demo only.

---

## Step 1 — Copy the Payments App

Copy the entire `payments/` directory into the root of the main project:

```
main_skillcraft_project/
├── manage.py
├── config/ (or skillcraft/ etc.)
├── courses/
├── enrollments/
├── accounts/
└── payments/          ← Copy this entire folder here
```

---

## Step 2 — Install Dependencies

Add these to the main project's `requirements.txt`:

```txt
razorpay>=1.4,<2.0
djangorestframework>=3.14,<4.0
djangorestframework-simplejwt>=5.0,<6.0
python-dotenv>=1.0,<2.0
```

Then run:
```bash
pip install -r requirements.txt
```

> **Note:** `django` and `djangorestframework` are likely already installed. Add only what is missing.

---

## Step 3 — Add to `INSTALLED_APPS`

In the main project's `settings.py`:

```python
INSTALLED_APPS = [
    # ... existing apps ...
    "rest_framework",          # if not already present
    "rest_framework_simplejwt", # if not already present
    "payments",                # ← Add this
]
```

---

## Step 4 — Configure REST Framework

If the main project does not already have DRF settings, add:

```python
from datetime import timedelta

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
}
```

---

## Step 5 — Add URL Routes

In the main project's `urls.py`:

```python
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # ... existing routes ...
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/payments/", include("payments.urls")),  # ← Add this
]
```

---

## Step 6 — Configure the Custom User Model

The payments app uses `settings.AUTH_USER_MODEL` automatically. If the main project has a custom User model, make sure it is set **before** running migrations:

```python
# In settings.py
AUTH_USER_MODEL = "accounts.CustomUser"  # or whatever your custom model is
```

No changes to the payments app code are needed.

---

## Step 7 — Add Payment Settings to `settings.py`

Copy this block into the main project's `settings.py`:

```python
import os

# ── Razorpay credentials ────────────────────────────────────────────────────
# Always loaded from environment variables — never hardcoded.
# Use Test Mode keys (starting with rzp_test_) during development.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# ── Payments app adapter settings ───────────────────────────────────────────
# See Step 8 and Step 9 below for how to create these adapters.
PAYMENTS_COURSE_CATALOG_ADAPTER = "courses.payment_adapters.SkillCraftCourseCatalogAdapter"
PAYMENTS_ENROLLMENT_ADAPTER = "enrollments.payment_adapters.SkillCraftEnrollmentAdapter"

# ── Combo package mapping ───────────────────────────────────────────────────
# List of real course IDs included in the Complete Combo Package.
# These must match the primary keys (or slugs/UUIDs) used by your Course model.
PAYMENTS_COMBO_COURSE_IDS = [1, 2, 3, 4, 5]  # ← Replace with real course IDs

# ── Optional settings (defaults shown) ─────────────────────────────────────
PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS = True   # auto-capture authorized payments
PAYMENTS_ORDER_REUSE_MINUTES = 30             # reuse an identical unpaid order within N minutes
PAYMENTS_HISTORY_PAGE_SIZE = 10               # default page size for payment history
```

---

## Step 8 — Connect the Real Course Model

Create a file `courses/payment_adapters.py` in the main project:

```python
"""
LMS → Payments bridge: Course catalog adapter.

The payments app never imports Course directly. It calls this adapter
to check if a course exists and can be purchased.
"""
from payments.adapters.base import BaseCourseCatalogAdapter, CourseInfo

from .models import Course  # ← Your actual Course model


class SkillCraftCourseCatalogAdapter(BaseCourseCatalogAdapter):

    def get_course(self, course_id):
        """
        Return CourseInfo if the course can be purchased, else None.
        
        Adjust the lookup field to match your Course model's identifier.
        Common options:
            Course.objects.filter(id=course_id, is_active=True)      # integer PK
            Course.objects.filter(slug=course_id, is_published=True)  # slug
            Course.objects.filter(uuid=course_id, is_active=True)     # UUID
        """
        try:
            # Using integer primary key (most common case):
            course = Course.objects.get(id=int(course_id), is_active=True)
            return CourseInfo(
                course_id=str(course.id),
                title=course.title,       # ← Adjust to your field name
            )
        except (Course.DoesNotExist, ValueError, TypeError):
            return None

    def get_combo_course_ids(self):
        """
        Return the list of course IDs included in the combo package.
        Read from settings so the team can update it without code changes.
        """
        from django.conf import settings
        return [str(cid) for cid in getattr(settings, "PAYMENTS_COMBO_COURSE_IDS", [])]
```

---

## Step 9 — Connect the Real Enrollment Model

Create `enrollments/payment_adapters.py`:

```python
"""
LMS → Payments bridge: Enrollment adapter.

Called ONLY after a payment is confirmed as captured by Razorpay.
Must be idempotent (safe to call multiple times — use get_or_create).
"""
from payments.adapters.base import BaseEnrollmentAdapter

from .models import Enrollment         # ← Your Enrollment model
from courses.models import Course      # ← Your Course model

# Optional: import CourseProgress if your LMS has it
# from .models import CourseProgress


class SkillCraftEnrollmentAdapter(BaseEnrollmentAdapter):

    def user_has_access(self, *, user, course_ids):
        """
        Return True if user already has access to ALL of the given courses.
        Used to prevent students from purchasing a course they already own.
        """
        if not course_ids:
            return False
        active_enrollments = Enrollment.objects.filter(
            student=user,          # ← Adjust field name
            course__id__in=course_ids,
            is_active=True,        # ← Adjust field name
        ).values_list("course_id", flat=True)
        enrolled_ids = {str(eid) for eid in active_enrollments}
        return all(str(cid) in enrolled_ids for cid in course_ids)

    def activate_enrollment(self, *, user, order, course_ids):
        """
        Grant access to every course in course_ids.
        
        Rules:
        - Called inside a database transaction (savepoint).
        - Must be IDEMPOTENT: use get_or_create / update_or_create.
        - Raise an exception if anything fails (the payment stays recorded;
          run 'python manage.py retry_enrollments' to retry).
        """
        for course_id in course_ids:
            try:
                course = Course.objects.get(id=int(course_id))
            except (Course.DoesNotExist, ValueError):
                raise ValueError(f"Course {course_id!r} not found during enrollment.")

            # Activate enrollment (adjust field names to your model)
            enrollment, created = Enrollment.objects.get_or_create(
                student=user,          # ← Adjust to your FK field name
                course=course,
                defaults={"is_active": True},
            )
            if not created and not enrollment.is_active:
                enrollment.is_active = True
                enrollment.save(update_fields=["is_active"])

            # Optional: Create a CourseProgress record
            # CourseProgress.objects.get_or_create(
            #     student=user,
            #     course=course,
            #     defaults={"progress_percentage": 0},
            # )
```

---

## Step 10 — Configure Environment Variables

Add these to the main project's `.env` file:

```env
# Razorpay (Test Mode during development, Live Mode in production)
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
RAZORPAY_WEBHOOK_SECRET=your_razorpay_webhook_secret
```

---

## Step 11 — Run Migrations

```bash
python manage.py makemigrations payments
python manage.py migrate
```

> If the main project already has existing payment-related migrations, see [Handling Existing Payment Models](#handling-existing-payment-models) below.

---

## Step 12 — Configure the Razorpay Webhook

1. Go to [Razorpay Dashboard](https://dashboard.razorpay.com) → Settings → Webhooks.
2. Add a new webhook:
   - **URL:** `https://your-production-domain.com/api/payments/webhook/`
   - **Secret:** Use `RAZORPAY_WEBHOOK_SECRET` from your `.env`
   - **Active events:** `payment.captured`, `payment.failed`, `order.paid`
3. For local development, use ngrok:
   - Install: `pip install ngrok` or download from https://ngrok.com
   - Run: `ngrok http 8000`
   - Use the HTTPS URL as the webhook URL

---

## Step 13 — Run System Check

```bash
python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

---

## Step 14 — Retry Failed Enrollments

If the LMS adapter fails during enrollment (e.g., database connection issue), the payment is still recorded as paid. Run this command to retry:

```bash
python manage.py retry_enrollments

# Preview without making changes
python manage.py retry_enrollments --dry-run
```

This is safe to run as a cron job:
```bash
# /etc/cron.d/skillcraft-retry-enrollments
*/15 * * * * /path/to/venv/bin/python /path/to/manage.py retry_enrollments
```

---

## Handling Existing Payment Models

If the main SkillCraft.AI project already has payment-related models or apps:

### Option A — The main project has no payment models yet
Just follow the steps above. Run `python manage.py migrate` and you are done.

### Option B — The main project has incomplete payment models
1. **Do NOT delete existing migrations** — that would break the production database.
2. Create a migration that renames or removes the old tables (use `SeparateDatabaseAndState` if needed).
3. Contact the team leader to review before running in production.

### Option C — The main project already has a complete payment implementation
If another developer already implemented payments, discuss with the team leader which implementation to keep. **Do not run both payment apps simultaneously.**

---

## Settings Summary

| Setting | Required | Description |
|---|---|---|
| `RAZORPAY_KEY_ID` | ✅ | Razorpay public key (prefix: `rzp_test_` or `rzp_live_`) |
| `RAZORPAY_KEY_SECRET` | ✅ | Razorpay secret key — NEVER expose this |
| `RAZORPAY_WEBHOOK_SECRET` | ✅ | Webhook secret from Razorpay Dashboard |
| `PAYMENTS_COURSE_CATALOG_ADAPTER` | ✅ | Dotted path to your CourseCatalogAdapter class |
| `PAYMENTS_ENROLLMENT_ADAPTER` | ✅ | Dotted path to your EnrollmentAdapter class |
| `PAYMENTS_COMBO_COURSE_IDS` | ✅ | List of course IDs in the combo package |
| `PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS` | Optional | Default: `True` |
| `PAYMENTS_ORDER_REUSE_MINUTES` | Optional | Default: `30` |
| `PAYMENTS_HISTORY_PAGE_SIZE` | Optional | Default: `10` |

---

## Files to Change vs. Files to Keep

### Files that MUST be adapted for the main project

| File | What to Change |
|---|---|
| `courses/payment_adapters.py` (new) | Create this — connects Course model |
| `enrollments/payment_adapters.py` (new) | Create this — connects Enrollment model |
| Main `settings.py` | Add the payments settings block |
| Main `urls.py` | Add the payments URL route |
| Main `requirements.txt` | Add razorpay, simplejwt, python-dotenv |
| Main `.env` | Add RAZORPAY_* variables |

### Files in `payments/` that should NOT be modified

All files in the `payments/` directory should remain unchanged to make future updates easier. The adapter pattern is specifically designed so the main project customizes behavior without touching the payment code.
