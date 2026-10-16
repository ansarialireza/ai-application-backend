import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-development-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.assistants",
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

ROOT_URLCONF = "ai_backend.urls"
WSGI_APPLICATION = "ai_backend.wsgi.application"
ASGI_APPLICATION = "ai_backend.asgi.application"
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

database_url = env("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {"default": env.db_url_config(database_url)}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"]["OPTIONS"] = {"timeout": 20}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.ApiKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.api_errors.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_RATES": {
        "public_execute": env("PUBLIC_EXECUTION_RATE", default="10/minute"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AI Application Backend API",
    "DESCRIPTION": "Tenant-scoped assistant configuration, conversation, and generation API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

RAG_CORE_BASE_URL = env("RAG_CORE_BASE_URL", default="http://127.0.0.1:8000").rstrip("/")
RAG_CONNECT_TIMEOUT_SECONDS = env.float("RAG_CONNECT_TIMEOUT_SECONDS", default=5.0)
RAG_READ_TIMEOUT_SECONDS = env.float("RAG_READ_TIMEOUT_SECONDS", default=30.0)
AI_PROVIDER_API_BASE_URL = env("AI_PROVIDER_API_BASE_URL", default="https://api.openai.com/v1").rstrip("/")
AI_PROVIDER_API_KEY = env("AI_PROVIDER_API_KEY", default="")
AI_PROVIDER_TIMEOUT_SECONDS = env.float("AI_PROVIDER_TIMEOUT_SECONDS", default=60.0)
MAX_INPUT_CHARS = env.int("MAX_INPUT_CHARS", default=20000)
MAX_HISTORY_MESSAGES = env.int("MAX_HISTORY_MESSAGES", default=20)
MAX_OUTPUT_TOKENS = env.int("MAX_OUTPUT_TOKENS", default=4096)
MAX_HISTORY_CHARS = env.int("MAX_HISTORY_CHARS", default=40000)
MAX_RAG_CONTEXT_CHARS = env.int("MAX_RAG_CONTEXT_CHARS", default=24000)
DATA_UPLOAD_MAX_MEMORY_SIZE = max(262144, MAX_INPUT_CHARS * 8)
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
