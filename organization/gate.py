"""Runtime feature access policy, configurable without editing source."""
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from .permissions import has_permission, view_permission
from .panels import PANEL_KEYS, panel_available


def feature_required(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not settings.FEATURE_OPEN_TO_ALL and not request.user.is_superuser:
            raise PermissionDenied("功能尚未對全體同仁開放")
        permission = view_permission(view.__module__, view.__name__)
        panel = permission.split(".")[0] if permission else None
        if panel in PANEL_KEYS and not panel_available(request.user, panel):
            raise PermissionDenied("此面板仍在開發中或尚未開放，請聯絡系統管理員。")
        if permission and not has_permission(request.user, permission):
            raise PermissionDenied("您的部門或個人設定未開放此功能，請聯絡系統管理員。")
        return view(request, *args, **kwargs)
    return inner
