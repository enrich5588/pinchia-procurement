import os
from pathlib import Path

from config.env import env_bool, env_list, load_env

BASE_DIR = Path(__file__).resolve().parents[2]
load_env(BASE_DIR / ".env")
FEATURE_OPEN_TO_ALL = env_bool("FEATURE_OPEN_TO_ALL", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "organization.apps.ProjectAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "organization.apps.OrganizationConfig",
    "procurement",
    "assets",
    "collaboration_hub",
    "approval_hub",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "organization.audit_middleware.OperationAuditMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "organization.shell.shell_context",
    ]},
}]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
                         "OPTIONS": {"timeout": 20}, "ATOMIC_REQUESTS": True}}

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Import previews are bounded at 500 rows by the application.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "private-media"))
ASSET_IMAGE_ROOT = MEDIA_ROOT / "assets"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Microsoft Entra single-tenant sign-in. Credentials remain on the server.
M365_TENANT_ID = os.environ.get("M365_TENANT_ID", "").strip()
M365_CLIENT_ID = os.environ.get("M365_CLIENT_ID", "").strip()
M365_CLIENT_SECRET = os.environ.get("M365_CLIENT_SECRET", "")
M365_CERT_PRIVATE_KEY_PATH = os.environ.get("M365_CERT_PRIVATE_KEY_PATH", "")
M365_CERT_THUMBPRINT = os.environ.get("M365_CERT_THUMBPRINT", "").strip()
M365_REDIRECT_URI = os.environ.get("M365_REDIRECT_URI", "").strip()
M365_ALLOW_GUESTS = env_bool("M365_ALLOW_GUESTS", False)
M365_DEPARTMENT_SYNC_ENABLED = env_bool("M365_DEPARTMENT_SYNC_ENABLED", True)
M365_DEPARTMENT_SYNC_SECONDS = max(60, int(os.environ.get("M365_DEPARTMENT_SYNC_SECONDS", "21600")))
# Only the verified Graph UPN in the configured tenant can receive this role.
M365_DEFAULT_ADMIN_UPN = os.environ.get("M365_DEFAULT_ADMIN_UPN", "tonychi@pin-chia.com").strip().casefold()
ALLOW_LOCAL_LOGIN = env_bool("ALLOW_LOCAL_LOGIN", False)
AUTHENTICATION_BACKENDS = ["organization.backends.MicrosoftBackend"]
if ALLOW_LOCAL_LOGIN:
    AUTHENTICATION_BACKENDS.append("django.contrib.auth.backends.ModelBackend")

# Enable only behind a proxy that strips client-supplied forwarding headers.
if env_bool("DJANGO_TRUST_PROXY_HTTPS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
