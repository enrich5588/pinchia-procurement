from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class ProjectAdminConfig(AdminConfig):
    default_site = "organization.admin_site.MicrosoftAdminSite"


class OrganizationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "organization"
    # Keep the existing table names, migration history and content types.
    label = "platform_stub"
    verbose_name = "組織與帳號"

    def ready(self):
        from . import signals  # noqa: F401
        from .audit import install
        install()
