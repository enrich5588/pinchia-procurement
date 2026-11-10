from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("local-", "dev-", "django-insecure-")):
    raise ImproperlyConfigured("Production requires a unique DJANGO_SECRET_KEY of at least 50 characters")
if not env_list("DJANGO_ALLOWED_HOSTS") or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Production requires explicit DJANGO_ALLOWED_HOSTS")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
