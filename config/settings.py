import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _split_env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return url.strip().rstrip("/")


def _host_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return parsed.hostname or url.strip().removeprefix("https://").removeprefix("http://").split("/")[0]


SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-key-change-in-production")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = _split_env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

_INSECURE_SECRET_KEYS = {
    "",
    "django-insecure-dev-key-change-in-production",
    "change-me-in-production",
}
if not DEBUG:
    if SECRET_KEY in _INSECURE_SECRET_KEYS or len(SECRET_KEY) < 32:
        raise ImproperlyConfigured("Set a strong SECRET_KEY (32+ chars) when DEBUG=False.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "apps.accounts",
    "apps.geography",
    "apps.minerals",
    "apps.maps",
    "apps.subscriptions",
    "apps.payments",
    "apps.reports",
    "apps.analytics",
    "apps.compliance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.compliance.middleware.AuditMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", "tmdb"),
        "USER": os.getenv("DB_USER", "tm-user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.OptionalJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "600/hour",
        "user": "2000/hour",
        "auth": "30/hour",
        "otp_send": "8/hour",
        "otp_verify": "40/hour",
        "upload": "30/hour",
        "map_geojson": "300/hour",
    },
}

# Coordinate precision (decimal places) served to anonymous / free users on map
# layer geometry. Paid users, admins and mineral managers always get full
# resolution. 2 dp ≈ 1.1 km, 3 dp ≈ 110 m, 4 dp ≈ 11 m.
MAP_PREVIEW_COORD_DECIMALS = int(os.getenv("MAP_PREVIEW_COORD_DECIMALS", "2"))

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOWED_ORIGINS = _split_env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3085")
CORS_ALLOW_CREDENTIALS = True

NGROK_URL = os.getenv("NGROK_URL", "").strip().rstrip("/")
NGROK_API_URL = os.getenv("NGROK_API_URL", "").strip().rstrip("/")
NGROK_ALLOW_WILDCARD = os.getenv("NGROK_ALLOW_WILDCARD", "false").lower() in ("1", "true", "yes")

_ngrok_origins: list[str] = []
_ngrok_hosts: list[str] = []
for raw_url in (NGROK_URL, NGROK_API_URL):
    if not raw_url:
        continue
    origin = _origin_from_url(raw_url)
    host = _host_from_url(raw_url)
    if origin:
        _ngrok_origins.append(origin)
    if host:
        _ngrok_hosts.append(host)

if _ngrok_origins:
    CORS_ALLOWED_ORIGINS = list(dict.fromkeys([*CORS_ALLOWED_ORIGINS, *_ngrok_origins]))
if _ngrok_hosts:
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, *_ngrok_hosts]))
if NGROK_ALLOW_WILDCARD or DEBUG:
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, ".ngrok-free.app", ".ngrok.io"]))
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https://[\w-]+\.ngrok-free\.app$",
        r"^https://[\w-]+\.ngrok\.io$",
    ]

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3085")

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

if os.getenv("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.getenv("REDIS_URL"),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "terra-meta",
        }
    }

# Snippe payments (https://docs.snippe.sh/docs/)
SNIPPE_API_KEY = os.getenv("SNIPPE_API_KEY", "")
SNIPPE_BASE_URL = os.getenv("SNIPPE_BASE_URL", "https://api.snippe.sh")
SNIPPE_WEBHOOK_SECRET = os.getenv("SNIPPE_WEBHOOK_SECRET", "")
SNIPPE_REDIRECT_URL = os.getenv("SNIPPE_REDIRECT_URL", "")
SNIPPE_CANCEL_URL = os.getenv("SNIPPE_CANCEL_URL", "")

BACKEND_URL = os.getenv("BACKEND_URL", "").strip()
if not BACKEND_URL:
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        "https://terrameta.5ggeology.com,https://api.terrameta.5ggeology.com",
    ).split(","):
        origin = origin.strip()
        if "api." in origin:
            BACKEND_URL = origin.rstrip("/")
            break
if not BACKEND_URL:
    BACKEND_URL = "http://127.0.0.1:8085"

if not SNIPPE_REDIRECT_URL:
    SNIPPE_REDIRECT_URL = f"{FRONTEND_URL}/payment/callback"
if not SNIPPE_CANCEL_URL:
    SNIPPE_CANCEL_URL = f"{FRONTEND_URL}/subscriptions"

# Aerial map analysis: included km² per view and price per extra km² (TZS).
AERIAL_INCLUDED_KM2 = float(os.getenv("AERIAL_INCLUDED_KM2", "10"))
AERIAL_PRICE_PER_KM2 = os.getenv("AERIAL_PRICE_PER_KM2", "10000")
AERIAL_MAX_BILLABLE_EXTRA_KM2 = float(os.getenv("AERIAL_MAX_BILLABLE_EXTRA_KM2", "500"))

# Local dev only: auto-complete checkout when Snippe is not configured.
PAYMENTS_SIMULATE = os.getenv("PAYMENTS_SIMULATE", "false").lower() in ("1", "true", "yes")
if not DEBUG and PAYMENTS_SIMULATE:
    raise ImproperlyConfigured("PAYMENTS_SIMULATE must not be enabled when DEBUG=False.")

# Max shapefile / GeoJSON upload size (bytes)
MAP_UPLOAD_MAX_BYTES = int(os.getenv("MAP_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
BOUNDARY_UPLOAD_MAX_BYTES = int(
    os.getenv("BOUNDARY_UPLOAD_MAX_BYTES", os.getenv("MAP_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
)
MAP_UPLOAD_MAX_FEATURES = int(os.getenv("MAP_UPLOAD_MAX_FEATURES", "50000"))
BOUNDARY_UPLOAD_MAX_FEATURES = int(os.getenv("BOUNDARY_UPLOAD_MAX_FEATURES", "100000"))
MAP_UPLOAD_MIN_FREE_BYTES = int(os.getenv("MAP_UPLOAD_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
BOUNDARY_IMPORT_MIN_FREE_BYTES = int(
    os.getenv("BOUNDARY_IMPORT_MIN_FREE_BYTES", os.getenv("MAP_UPLOAD_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
)
MAP_ZIP_MAX_ENTRIES = int(os.getenv("MAP_ZIP_MAX_ENTRIES", "200"))
MAP_ZIP_MAX_UNCOMPRESSED_BYTES = int(os.getenv("MAP_ZIP_MAX_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024)))
MAP_ZIP_MAX_COMPRESSION_RATIO = int(os.getenv("MAP_ZIP_MAX_COMPRESSION_RATIO", "100"))
MAP_FEATURE_BULK_BATCH_SIZE = int(os.getenv("MAP_FEATURE_BULK_BATCH_SIZE", "25"))
MAP_FEATURE_MAX_BATCH_BYTES = int(os.getenv("MAP_FEATURE_MAX_BATCH_BYTES", str(1024 * 1024)))
MAP_FEATURE_MAX_GEOMETRY_BYTES = int(os.getenv("MAP_FEATURE_MAX_GEOMETRY_BYTES", str(512 * 1024)))

# Icon URL override for HTML emails (optional)
EMAIL_LOGO_URL = os.getenv("EMAIL_LOGO_URL", "").strip()

# Intelligence summaries - provider: ollama | groq | gemini (with comma-separated fallbacks)
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq")
AI_PROVIDER_FALLBACK = os.getenv("AI_PROVIDER_FALLBACK", "groq,gemini,ollama")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

CSRF_TRUSTED_ORIGINS = _split_env_list(
    "CSRF_TRUSTED_ORIGINS",
    "https://terrameta.5ggeology.com,https://api.terrameta.5ggeology.com",
)
if _ngrok_origins:
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, *_ngrok_origins]))

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.hostinger.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("1", "true", "yes")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() in ("1", "true", "yes")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "5G Geology <admin@5ggeology.com>")
