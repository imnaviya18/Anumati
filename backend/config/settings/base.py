"""Base settings for ANUMATI v2 modular monolith (Sheets 01, 05, 06, 07)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "change-me-in-production-anumati-v2-secret-key",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # ANUMATI v2 modular domain apps (Sheet 01 Blocks 01-12)
    "apps.common",
    "apps.accounts",
    "apps.access",
    "apps.organisation",
    "apps.cases",
    "apps.routing",
    "apps.evc",
    "apps.decisions",
    "apps.compliance",
    "apps.documents",
    "apps.policy",
    "apps.deadlines",
    "apps.escalation",
    "apps.notifications",
    "apps.communications",
    "apps.outbox",
    "apps.audit",
    "apps.reporting",
    "apps.adapters",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.common.middleware.CorrelationIdMiddleware",
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
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database configuration (Sheet 01 Block 10, Sheet 05)
USE_SQLITE_FALLBACK = os.environ.get("USE_SQLITE_FALLBACK", "false").lower() == "true"

if USE_SQLITE_FALLBACK:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 30,
                "transaction_mode": "IMMEDIATE",
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "anumati"),
            "USER": os.environ.get("POSTGRES_USER", "anumati_app"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "anumati_local_pass"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Session + CSRF security (Sheet 01 Block 01, Sheet 05, Sheet 07 P1)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:15173,http://127.0.0.1:15173",
    ).split(",")
    if origin.strip()
]
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", "26214400"))


REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# Celery / Redis broker only (Sheet 01 Block 08, Sheet 05)
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = "default"

# Private file storage & sealed audit exports (Sheet 01 Blocks 09, 11, Sheet 07 N5, P2)
PRIVATE_STORAGE_ROOT = Path(
    os.environ.get("PRIVATE_STORAGE_ROOT", str(BASE_DIR / "var" / "private_storage"))
)
SEALED_AUDIT_EXPORT_ROOT = Path(
    os.environ.get("SEALED_AUDIT_EXPORT_ROOT", str(BASE_DIR / "var" / "sealed_audit_exports"))
)
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", "26214400"))

# Email delivery: disabled by default; standard SMTP when enabled (NO EXTERNAL APIs Rule)
EMAIL_DELIVERY_ENABLED = os.environ.get("EMAIL_DELIVERY_ENABLED", "false").lower() == "true"
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_DELIVERY_ENABLED
    else "django.core.mail.backends.locmem.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@anumati.local")

# Disabled external adapter ports (Sheet 01 Block 12, Sheet 05, NO EXTERNAL APIs Rule)
ADAPTER_PORTS = {
    "aicte_erp": os.environ.get("ADAPTER_AICTE_ERP_ENABLED", "false").lower() == "true",
    "nsws_intake": os.environ.get("ADAPTER_NSWS_INTAKE_ENABLED", "false").lower() == "true",
    "sso_identity": os.environ.get("ADAPTER_SSO_ENABLED", "false").lower() == "true",
    "payment_gateway": os.environ.get("ADAPTER_PAYMENT_GATEWAY_ENABLED", "false").lower() == "true",
    "sms_gateway": False,  # Strictly disabled per NO SMS rule
    "external_scanner": os.environ.get("ADAPTER_EXTERNAL_SCANNER_ENABLED", "false").lower() == "true",
}

# Beat only triggers recoverable work; durable intent stays in PostgreSQL.
CELERY_BEAT_SCHEDULE = {
    "dispatch-outbox": {"task": "outbox.dispatch_batch", "schedule": 10.0},
    "recover-stranded": {"task": "outbox.recover_stranded", "schedule": 60.0},
    "scan-deadlines": {"task": "deadlines.scan_due", "schedule": 60.0},
}
EMAIL_TIMEOUT = 20

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

ALLOW_DEMONSTRATION_POLICIES = os.environ.get("ALLOW_DEMONSTRATION_POLICIES", "true").lower() == "true"

ALLOW_AUTHORITATIVE_POLICY_ACTIVATION = os.environ.get("ALLOW_AUTHORITATIVE_POLICY_ACTIVATION", "false").lower() == "true"
