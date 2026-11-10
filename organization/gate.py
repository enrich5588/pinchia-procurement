"""Runtime feature access policy, configurable without editing source."""
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied


def feature_required(view):
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not settings.FEATURE_OPEN_TO_ALL and not request.user.is_superuser:
            raise PermissionDenied("功能尚未對全體同仁開放")
        return view(request, *args, **kwargs)
    return inner
