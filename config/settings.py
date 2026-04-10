"""Django settings for gender classification API (stateless — no ORM / DB file)."""

SECRET_KEY = "django-insecure-change-me-in-production-use-env"

DEBUG = True

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

# No SQLite or migrations — this app does not use the database.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.dummy",
    }
}

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
