from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin import AdminSite
from django.shortcuts import redirect
from django.urls import reverse


class MicrosoftAdminSite(AdminSite):
    def has_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def login(self, request, extra_context=None):
        if settings.ALLOW_LOCAL_LOGIN:
            return super().login(request, extra_context)
        if self.has_permission(request):
            return redirect(reverse("admin:index"))
        return redirect(reverse("login") + "?" + urlencode({
            "next": request.GET.get("next", reverse("admin:index")),
        }))
