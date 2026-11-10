from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only-change-in-production")
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
