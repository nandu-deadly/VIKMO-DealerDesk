"""DealerDesk settings. Everything environment-specific comes from environment variables.

Required: DATABASE_URL (PostgreSQL). Also read: SUPPLIER_API_URL, SUPPLIER_API_KEY and one LLM key
(GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY or GROQ_API_KEY).
For local development you can put them in a .env file at the repo root (never commit it).
"""
import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")  # real environment variables always win over .env

# ---- Security & Execution Environment ------------------------------------------------
# DEBUG defaults to False (0) for deployment-safe behavior. Explicitly enabled via 1/true/yes.
DEBUG = os.environ.get("DJANGO_DEBUG", "0").strip().lower() in ("1", "true", "yes")

# Detect whether executing under Django's test runner or isolated testing environment
RUNNING_TESTS = (
    "test" in sys.argv
    or any("test" in arg for arg in sys.argv)
    or os.environ.get("DJANGO_TESTING") == "1"
)

# SECRET_KEY resolution: no insecure default constants like 'dev-only-insecure-key'
KNOWN_INSECURE_KEYS = {
    "dev-only-insecure-key",
    "change-me",
    "secret",
    "password",
    "insecure",
    "django-insecure",
}

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if RUNNING_TESTS:
        # Deliberately isolated test configuration secret (never used in production)
        SECRET_KEY = "django-insecure-test-runner-ephemeral-key-do-not-use-in-prod"
    else:
        raise ImproperlyConfigured(
            "Missing required DJANGO_SECRET_KEY environment variable. "
            "Please configure DJANGO_SECRET_KEY in your environment or .env file."
        )

# Ensure secret key meets minimum security criteria outside isolated test runners
if not RUNNING_TESTS:
    if SECRET_KEY in KNOWN_INSECURE_KEYS:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is set to a known insecure placeholder. "
            "Please set a strong, unique secret key."
        )
    if not DEBUG and len(SECRET_KEY) < 32:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be at least 32 characters in production (when DEBUG=False)."
        )

# ALLOWED_HOSTS: parsed from DJANGO_ALLOWED_HOSTS or ALLOWED_HOSTS
raw_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS") or os.environ.get("ALLOWED_HOSTS")
if raw_allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(",") if h.strip()]
elif DEBUG or RUNNING_TESTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
else:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

if "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")

# CSRF_TRUSTED_ORIGINS: parsed from DJANGO_CSRF_TRUSTED_ORIGINS
raw_csrf_trusted = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS") or os.environ.get("CSRF_TRUSTED_ORIGINS")
if raw_csrf_trusted:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in raw_csrf_trusted.split(",") if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []

# Hardening security headers in production (when DEBUG is False and not in tests)
if not DEBUG and not RUNNING_TESTS:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "core",
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

ROOT_URLCONF = "dealerdesk.urls"

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

WSGI_APPLICATION = "dealerdesk.wsgi.application"

# ---- Database: PostgreSQL only -------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    db_name = os.environ.get("PGDATABASE") or os.environ.get("DB_NAME")
    db_user = os.environ.get("PGUSER") or os.environ.get("DB_USER")
    db_password = os.environ.get("PGPASSWORD") or os.environ.get("DB_PASSWORD", "")
    db_host = os.environ.get("PGHOST") or os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("PGPORT") or os.environ.get("DB_PORT", "5432")
    if db_name and db_user:
        auth = f"{db_user}:{db_password}@" if db_password else f"{db_user}@"
        DATABASE_URL = f"postgresql://{auth}{db_host}:{db_port}/{db_name}"

if not DATABASE_URL:
    raise ImproperlyConfigured(
        "Set DATABASE_URL (or PGDATABASE, PGUSER, PGHOST, PGPORT) to a valid PostgreSQL URL."
    )

DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0)}
db_schema = os.environ.get("DB_SCHEMA")
if db_schema:
    existing_opts = DATABASES["default"].get("OPTIONS", {}).get("options", "")
    schema_opt = f"-c search_path={db_schema}"
    combined_opts = f"{existing_opts} {schema_opt}".strip()
    if "OPTIONS" not in DATABASES["default"]:
        DATABASES["default"]["OPTIONS"] = {}
    DATABASES["default"]["OPTIONS"]["options"] = combined_opts

test_db_name = os.environ.get("TEST_DATABASE_NAME")
if test_db_name:
    DATABASES["default"]["TEST"] = {"NAME": test_db_name}
if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured(
        "DealerDesk requires PostgreSQL. SQLite can't test the concurrency rules."
    )

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- API: Session Authentication with Role-Based Access Control --------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
}

# ---- Assignment settings --------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip().lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
SUPPLIER_API_URL = os.environ.get("SUPPLIER_API_URL", "http://127.0.0.1:8099").strip()
SUPPLIER_API_KEY = os.environ.get("SUPPLIER_API_KEY", "").strip()
