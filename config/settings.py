"""Django configuration: database, caching, CORS/CSRF, JWT auth, REST Framework.

Load-time env is read via python-dotenv so local and deployed instances share one layout.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "mtsecret")

DEBUG = os.environ.get("DEBUG", "true").lower() in ("1", "true", "yes")

ALLOWED_HOSTS: list[str] = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "corsheaders",
    "rest_framework",
    "accounts",
    "classify",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "accounts.middleware.ApiVersionMiddleware",
    "accounts.rate_limit_middleware.RateLimitMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.rate_limit_middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES: list[dict] = []

WSGI_APPLICATION = "config.wsgi.application"

_default_db_url = os.environ.get("DATABASE_URL", "").strip()

if _default_db_url:
    parsed = urlparse(_default_db_url)
    db_name = (parsed.path or "").lstrip("/")
    query = parse_qs(parsed.query)
    ssl_modes = query.get("sslmode") or query.get("ssl")
    # Long-running seed/migrations: ask PostgreSQL not to abort statements on connect.
    db_options: dict = {
        "options": "-c statement_timeout=0 -c lock_timeout=0",
    }
    if ssl_modes and ssl_modes[0]:
        db_options["sslmode"] = ssl_modes[0]
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_name or "postgres",
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": 60,
            "OPTIONS": db_options,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(os.path.dirname(os.path.dirname(__file__)), "db.sqlite3"),
        }
    }

# List/search responses use Django's cache. Postgres: DatabaseCache (shared workers, needs
# django_cache table). SQLite: LocMem (dev/tests, no setup).
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "django_cache",
            "TIMEOUT": 90,
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "insighta_profile_query_cache",
            "TIMEOUT": 90,
        }
    }

# Streaming CSV uploads: cap in-memory buffering; Django spills bigger bodies to TEMP.
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("DATA_UPLOAD_MAX_MEMORY_SIZE", str(200 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024))
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS: list[dict] = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Browser portal + credentials: explicit origins (http-only cookies + CSRF).
WEB_PORTAL_ORIGIN = os.environ.get(
    "WEB_PORTAL_ORIGIN", "http://localhost:5173"
).strip()

_cors_extra = os.environ.get("CORS_EXTRA_ORIGINS", "")
_default_origins = [
    WEB_PORTAL_ORIGIN.rstrip("/"),
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_origins_set: list[str] = []
for o in _default_origins + [p.strip() for p in _cors_extra.split(",") if p.strip()]:
    if o not in _origins_set:
        _origins_set.append(o)

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _origins_set
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "x-api-version")

# POST from another origin with cookies requires the host listed here plus CSRF token.
CSRF_TRUSTED_ORIGINS = _origins_set.copy()

# CSRF cookie flags: lax local dev; production uses None + Secure so SPAs can send csrftoken.
if DEBUG:
    CSRF_COOKIE_SECURE = False
    CSRF_COOKIE_SAMESITE = "Lax"
else:
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_SAMESITE = "None"

REST_FRAMEWORK = {
    # DRF gets JWT + django.contrib.auth (needed for AnonymousUser in throttles).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "accounts.permissions.IsActiveInsightaUser",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["accounts.throttles.ApiUserThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "api_user": "60/minute",
        "auth_burst": "10/minute",
    },
    "EXCEPTION_HANDLER": "accounts.exception_handlers.insighta_exception_handler",
}

# Portal uses GITHUB_CLIENT_*; insighta-cli uses GITHUB_CLI_* with loopback redirect.
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "").strip()
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
GITHUB_CLI_CLIENT_ID = os.environ.get("GITHUB_CLI_CLIENT_ID", "").strip()
GITHUB_CLI_CLIENT_SECRET = os.environ.get("GITHUB_CLI_CLIENT_SECRET", "").strip()
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY", "").strip()
BACKEND_PUBLIC_URL = os.environ.get(
    "BACKEND_PUBLIC_URL", "http://localhost:8000"
).strip()
INSIGHTA_CLI_OAUTH_REDIRECT = os.environ.get(
    "INSIGHTA_CLI_OAUTH_REDIRECT", "http://127.0.0.1:8765/callback"
).strip()

ACCESS_TOKEN_LIFETIME_SECONDS = int(
    os.environ.get("ACCESS_TOKEN_LIFETIME_SECONDS", "180")
)
REFRESH_TOKEN_LIFETIME_SECONDS = int(
    os.environ.get("REFRESH_TOKEN_LIFETIME_SECONDS", "300")
)

# Grader/manual flows: pretend GitHub approved a fixed authorization code (see README).
INSIGHTA_ENABLE_TEST_OAUTH_CODE = os.environ.get(
    "INSIGHTA_ENABLE_TEST_OAUTH_CODE", ""
).strip().lower() in ("1", "true", "yes")
INSIGHTA_TEST_OAUTH_CODE = os.environ.get(
    "INSIGHTA_TEST_OAUTH_CODE", "test_code"
).strip()
# When issuing test_code tokens: prefer this GitHub username as the admin subject.
GRADER_ADMIN_USERNAME = os.environ.get("GRADER_ADMIN_USERNAME", "").strip()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "accounts.rate_limit_middleware": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}
