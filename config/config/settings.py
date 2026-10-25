import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))


SECRET_KEY = os.environ.get('SECRET_KEY', "fallback_secret_key")
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost,0.0.0.0").split(",") if host.strip()]
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8000").rstrip("/")

CUSTOMIZER_UPLOAD_PRICE = int(os.environ.get("CUSTOMIZER_UPLOAD_PRICE", "0"))
CUSTOMIZER_MAX_UPLOAD_BYTES = int(os.environ.get("CUSTOMIZER_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
CUSTOMIZER_TEMP_ROOT = Path(os.environ.get("CUSTOMIZER_TEMP_ROOT", str(BASE_DIR / "data" / "customizer_tmp")))

INSTALLED_APPS = [
    "apps.users.admin_apps.BabaeiAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "phonenumber_field",
    "axes",
    "tinymce",
    "apps.home",
    "apps.users",
    "apps.shop",
    "apps.orders",
    "apps.marketplace.apps.MarketplaceConfig",
    "apps.customizer",
    "apps.saved",
    "apps.control_center",
    "apps.backups",
]

INTERNAL_IPS = ['127.0.0.1']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    "django.middleware.locale.LocaleMiddleware",
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.control_center.middleware.ControlAuditMiddleware',
]
ROOT_URLCONF = 'config.urls'

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.debug', 'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages', 'apps.orders.context_processors.cart_context', 'apps.shop.context_processors.designer_navigation']}}]
# Keep local development simple with SQLite. Inside Docker, use the
# PostgreSQL service from docker-compose instead of a host-local database.
RUNNING_IN_DOCKER = os.path.exists("/.dockerenv")
DATABASE_URL = os.environ.get("DATABASE_URL")

if RUNNING_IN_DOCKER:
    if DATABASE_URL:
        database_config = dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
        if database_config.get("HOST") in {"127.0.0.1", "localhost"}:
            database_config["HOST"] = "postgres"
        DATABASES = {"default": database_config}
    else:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.environ.get("POSTGRES_DB", "babaei"),
                "USER": os.environ.get("POSTGRES_USER", "babaei"),
                "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "supersecretpassword"),
                "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
                "PORT": os.environ.get("POSTGRES_PORT", "5432"),
                "CONN_MAX_AGE": 600,
                "CONN_HEALTH_CHECKS": True,
            }
        }
else:
    # SQLite cannot create a database when its parent directory is missing.
    # Docker creates this path through the data volume; CI and fresh local
    # checkouts need the directory to exist before Django opens the connection.
    SQLITE_PATH = BASE_DIR / "data" / "database" / "db.sqlite3"
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_PATH,
            "TEST": {"NAME": ":memory:"},
        }
    }

# Sessions are backed by Redis. The Redis hostname must match the Docker
# Compose service name when Django/Celery run inside containers.
redis_url = os.environ.get(
    "REDIS_URL",
    "redis://redis:6379/0" if RUNNING_IN_DOCKER else "redis://127.0.0.1:6379/0",
)
if RUNNING_IN_DOCKER and redis_url.startswith(("redis://127.0.0.1:", "redis://localhost:")):
    redis_url = redis_url.replace("redis://127.0.0.1:", "redis://redis:", 1)
    redis_url = redis_url.replace("redis://localhost:", "redis://redis:", 1)

redis_cache_url = os.environ.get(
    "REDIS_CACHE_URL",
    "redis://redis:6379/1" if RUNNING_IN_DOCKER else "redis://127.0.0.1:6379/1",
)
if RUNNING_IN_DOCKER and redis_cache_url.startswith(("redis://127.0.0.1:", "redis://localhost:")):
    redis_cache_url = redis_cache_url.replace("redis://127.0.0.1:", "redis://redis:", 1)
    redis_cache_url = redis_cache_url.replace("redis://localhost:", "redis://redis:", 1)

CELERY_BROKER_URL = redis_url
CELERY_TIMEZONE = os.environ.get("CELERY_TIMEZONE", "Asia/Tehran")
CELERY_ENABLE_UTC = True
CELERY_TASK_IGNORE_RESULT = True

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# Authentication views in this project live under /login/, not Django's
# default /accounts/login/. This keeps @login_required redirects consistent
# with the actual users URL configuration.
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/account/"
LOGOUT_REDIRECT_URL = "/login/"

AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en'
USE_I18N = True
TIME_ZONE = 'UTC'
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / 'locale']
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "data/static/"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "data/media/"
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'users.User'
PHONE_NUMBER_DEFAULT_REGION = "IR"
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(hours=1)
AXES_CACHE = 'default'
AUTHENTICATION_BACKENDS = ["apps.users.backends.BabaeiAxesBackend", "django.contrib.auth.backends.ModelBackend"]
CACHES = {"default": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": redis_cache_url, "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"}}}
# Ensure the log directory exists before Django configures FileHandler.
LOG_DIR = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {"version": 1, "disable_existing_loggers": False, "formatters": {"verbose": {"format": "{asctime} | {levelname} | {name} | {message}", "style": "{"}}, "filters": {}, "handlers": {"console": {"level": "INFO", "class": "logging.StreamHandler", "formatter": "verbose"}, "file": {"level": "INFO", "class": "logging.handlers.RotatingFileHandler", "filename": "data/logs/application.log", "maxBytes": 1024 * 1024 * 5, "backupCount": 5, "formatter": "verbose"}}, "loggers": {"apps": {"handlers": ["console", "file"], "level": "INFO", "propagate": False}}}


# Backup scheduling is evaluated frequently; the database settings decide
# whether the current run is due, so changing the schedule in Control Center
# takes effect without rebuilding the containers.
CELERY_BEAT_SCHEDULE = {
    "backup-schedule-check": {
        "task": "backups.run_scheduled_backup_check",
        "schedule": 300.0,
    },
    "cleanup-expired-otps": {
        "task": "apps.users.tasks.cleanup_expired_otps",
        "schedule": 3600.0,
    },
    "cleanup-stale-uploaded-artworks": {
        "task": "apps.customizer.tasks.cleanup_stale_uploaded_artworks",
        "schedule": 21600.0,
    },
    "cleanup-orphan-customizer-temp-files": {
        "task": "apps.customizer.tasks.cleanup_orphan_customizer_temp_files",
        "schedule": 21600.0,
    },
    "cleanup-stale-design-drafts": {
        "task": "apps.customizer.tasks.cleanup_stale_design_drafts",
        "schedule": 21600.0,
    },
    "cleanup-orphan-media": {
        "task": "apps.customizer.tasks.cleanup_orphan_media",
        "schedule": 21600.0,
    },
    "create-daily-vendor-settlement-batches": {
        "task": "apps.marketplace.tasks.create_daily_settlement_batches_task",
        "schedule": crontab(minute=0, hour=23),
    },
    "refresh-active-marketplace-shipments": {
        "task": "apps.marketplace.tasks.refresh_active_shipments_task",
        "schedule": 1800.0,
    },
}
