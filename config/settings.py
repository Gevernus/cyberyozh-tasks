"""
Django settings for the task management API.

All environment-specific values come from environment variables. Defaults are
tuned for local development (SQLite, DEBUG on); production requires
DJANGO_SECRET_KEY to be set explicitly.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
import sentry_sdk
from django.core.exceptions import ImproperlyConfigured

from core.observability import JSON_FORMATTER

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def env_float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", default=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG is off.")
    SECRET_KEY = "django-insecure-local-development-key"  # nosec B105

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# The admin login has no rate limit, so in production it is off unless asked for.
ADMIN_ENABLED = env_bool("DJANGO_ADMIN_ENABLED", default=DEBUG)
ADMIN_URL = (os.environ.get("DJANGO_ADMIN_URL", "").strip("/") or "admin") + "/"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_prometheus",
    # Local
    "apps.accounts",
    "apps.tasks",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "core.observability.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
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

# SQLite by default; PostgreSQL via DATABASE_URL=postgres://user:pass@host:5432/db
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        # A persistent connection is held per gunicorn thread: workers * threads
        # connections in total must stay below PostgreSQL's max_connections.
        conn_max_age=env_int("DJANGO_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}

# A runaway query is cancelled instead of holding a worker thread and a connection.
# 0 disables the limit, e.g. for migrations and bulk loads.
DB_STATEMENT_TIMEOUT_MS = env_int("DJANGO_DB_STATEMENT_TIMEOUT_MS", 5000)
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql" and DB_STATEMENT_TIMEOUT_MS:
    DATABASES["default"].setdefault("OPTIONS", {})["options"] = (
        f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"
    )

# Throttle counters must be shared by all gunicorn processes, hence Redis in
# production. LocMem is per-process and only suits local runs and tests.
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            # redis-py waits forever by default; fail fast instead of hanging a worker.
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    # Fail open: while the cache is unreachable requests pass without rate limits.
    # Auth endpoints add their own limits, see apps/accounts/views.py.
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.FailOpenAnonRateThrottle",
        "core.throttling.FailOpenUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("THROTTLE_ANON_RATE", "100/hour"),
        "user": os.environ.get("THROTTLE_USER_RATE", "1000/hour"),
        "auth": os.environ.get("THROTTLE_AUTH_RATE", "10/min"),
        "auth_account_ip": os.environ.get("THROTTLE_AUTH_ACCOUNT_IP_RATE", "10/hour"),
        "auth_account": os.environ.get("THROTTLE_AUTH_ACCOUNT_RATE", "100/hour"),
    },
    # 0 = identify clients by the socket address. Without it DRF trusts any
    # X-Forwarded-For value, so a client could dodge throttling by forging the header.
    # Set to the number of reverse proxies in front of the app.
    "NUM_PROXIES": env_int("NUM_PROXIES", 0),
    "DEFAULT_SCHEMA_CLASS": "core.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# Access tokens are not revocable, so they are short-lived. Refresh tokens are
# single-use: each refresh returns a new one and blacklists the old, and logout
# blacklists the current one. Run `manage.py flushexpiredtokens` daily.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_TOKEN_MINUTES", 15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_TOKEN_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Task Management API",
    "DESCRIPTION": (
        "REST API for managing tasks: create, edit, delete, assign to other users, "
        "mark as completed and discuss in comments. Requests carry a JWT access token: "
        "`Authorization: Bearer <token>`. In Swagger UI, get a token from "
        "`POST /api/auth/token/`, press Authorize and paste the access token without "
        "the `Bearer` prefix."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/",
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
    # Served from our static files, not a CDN, so the CSP can stay at 'self'.
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
}

# --- Security --------------------------------------------------------------
# Django's defaults, pinned so the policy is visible in one place.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True

if env_bool("DJANGO_SECURE_PROXY_SSL_HEADER", default=False):
    # Only safe behind a proxy that always overwrites X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Off by default: the compose setup serves plain HTTP. Turn on once TLS terminates
# in front of the app.
if env_bool("DJANGO_SECURE_HTTPS", default=False):
    SECURE_SSL_REDIRECT = True
    # Health checks and metric scrapes talk plain HTTP inside the private network.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/(live/)?$", r"^metrics$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31_536_000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)

# --- Logging ---------------------------------------------------------------
# JSON lines on stdout for the container runtime to collect, each tagged with the
# request id. Django's default handlers are dropped: with DEBUG off they only mail
# ADMINS, so 500s were invisible.
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "core.observability.RequestIdFilter"}},
    "formatters": {"json": JSON_FORMATTER},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": [], "level": LOG_LEVEL, "propagate": True},
        # 5xx with tracebacks; 4xx are already in the gunicorn access log.
        "django.request": {"level": "ERROR"},
        "django.security": {"level": "WARNING"},
    },
}

# --- Error tracking ----------------------------------------------------------
# Off unless SENTRY_DSN is set. Request bodies, cookies and user details stay out.
if SENTRY_DSN := os.environ.get("SENTRY_DSN", ""):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        send_default_pii=False,
    )
