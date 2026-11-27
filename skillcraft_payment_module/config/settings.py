"""
Django settings for the SkillCraft.AI payment module STANDALONE DEMO project.

This project exists only so the reusable `payments` app can be run, tested
and demonstrated on its own. When the app is integrated into the main
SkillCraft.AI project, only the settings in the "PAYMENTS MODULE SETTINGS"
section below need to be copied (see docs/MAIN_PROJECT_INTEGRATION.md).

All secrets are read from environment variables (loaded from a `.env` file).
Nothing secret is hardcoded in this file.
"""
import os
import warnings
from datetime import timedelta
from pathlib import Path

from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from the .env file in the project root (if it exists).
# Real environment variables always take priority over the .env file.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read a True/False value from an environment variable."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Read a comma separated list from an environment variable."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core Django settings
# ---------------------------------------------------------------------------
DEBUG = env_bool("DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Local development convenience: generate a throw-away random key.
        # (Sessions/JWTs become invalid every time the server restarts.)
        SECRET_KEY = get_random_secret_key()
        warnings.warn(
            "DJANGO_SECRET_KEY is not set. A temporary random key is being "
            "used. Set DJANGO_SECRET_KEY in your .env file.",
            stacklevel=1,
        )
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DEBUG is False."
        )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# ngrok / cloudflared tunnels used for local webhook testing.
# Add your tunnel host to ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS in .env.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    # Reusable SkillCraft.AI payments module
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# SQLite is used by default (no setup needed).
# Set POSTGRES_DB (and friends) in .env to use PostgreSQL instead.
# ---------------------------------------------------------------------------
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "ATOMIC_REQUESTS": False,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The payments app always refers to settings.AUTH_USER_MODEL, so it works
# with the main project's custom user model. The demo uses Django's default.
# AUTH_USER_MODEL = "accounts.User"   # <- example for the main project

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework (demo project configuration)
# The payments app does NOT depend on these exact classes: it uses whatever
# authentication the main project configures.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Postman / mobile / SPA clients: "Authorization: Bearer <access_token>"
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Browsable API / admin users. DRF enforces CSRF for session auth.
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

# ---------------------------------------------------------------------------
# PAYMENTS MODULE SETTINGS  (copy this block into the main project)
# ---------------------------------------------------------------------------
# Razorpay credentials - ALWAYS from environment variables, never hardcoded.
# Use Test Mode keys (they start with "rzp_test_") during development.
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# Adapters connect the payment module to the LMS.
# DEMO adapters are used here because this standalone project has no real
# Course / Enrollment models. The main project must point these to its own
# adapter classes (see docs/MAIN_PROJECT_INTEGRATION.md).
PAYMENTS_COURSE_CATALOG_ADAPTER = "payments.adapters.demo.DemoCourseCatalogAdapter"
PAYMENTS_ENROLLMENT_ADAPTER = "payments.adapters.demo.DemoEnrollmentAdapter"

# DEMO PLACEHOLDER: course identifiers included in the Complete Combo Package.
# These IDs refer to the demo catalog in payments/adapters/demo.py and are NOT
# the real SkillCraft.AI combo. The main LMS must supply the real list.
PAYMENTS_COMBO_COURSE_IDS = env_list("PAYMENTS_COMBO_COURSE_IDS", "11,12,13,14,15")

# Optional: if Razorpay leaves a payment in "authorized" state (auto-capture
# disabled in the Dashboard), the backend captures it during verification.
PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS = env_bool(
    "PAYMENTS_CAPTURE_AUTHORIZED_PAYMENTS", default=True
)

# ---------------------------------------------------------------------------
# Logging - payment logs never contain secrets, signatures or card details.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "payments": {
            "handlers": ["console"],
            "level": os.environ.get("PAYMENTS_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Production hardening (active automatically when DEBUG=False)
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
