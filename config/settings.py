"""Django settings — Stage 1 profiles API with PostgreSQL."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "mtsecret")

DEBUG = os.environ.get("DEBUG", "true").lower() in ("1", "true", "yes")

ALLOWED_HOSTS: list[str] = ["*"]

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "classify",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
    # libpq: request no statement timeout on connect. Many hosts still cap; seed also uses tiny batches.
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS: list[dict] = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Grading / browser clients: allow any origin
CORS_ALLOW_ALL_ORIGINS = True

REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
}
