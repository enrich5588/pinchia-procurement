"""Department defaults with explicit per-person overrides. No long-lived cache."""
from django.db.models import Q

from .models import PermissionRule, user_department
from .permission_catalog import DEFAULTS
from .panels import PANEL_KEYS, panel_available


def resolve_permission(user, code):
    if code not in DEFAULTS or not getattr(user, "is_authenticated", False) or not user.is_active:
        return False, "未登入、停用或未知權限"
    if user.is_superuser:
        return True, "系統管理員"
    if code == "database.monitor":
        return False, "系統管理員專用"
    panel = code.split(".")[0]
    if panel in PANEL_KEYS and not panel_available(user, panel):
        return False, "面板未開放"
    department = user_department(user)
    targets = Q(user_id=user.pk)
    if department:
        targets |= Q(department_id=department.pk)
    rules = list(PermissionRule.objects.filter(targets, permission=code).values("user_id", "effect"))
    personal = next((rule for rule in rules if rule["user_id"] == user.pk), None)
    if personal:
        return personal["effect"] == "allow", "個人設定"
    if rules:
        return rules[0]["effect"] == "allow", "部門設定"
    return DEFAULTS[code], "系統預設"


def has_permission(user, code):
    return resolve_permission(user, code)[0]


def can_manage(user, module):
    return has_permission(user, f"{module}.access") and has_permission(user, f"{module}.manage")


def view_permission(module, name):
    if module == "procurement.views":
        return "equipment.access" if name.startswith("equipment") else "supplies.access"
    if module == "assets.views":
        if name == "database_monitor":
            return "database.monitor"
        return "registrations.access" if name.startswith("registration") else "assets.access"
    if module == "collaboration_hub.views":
        return "collaboration.access"
    if module == "approval_hub.views":
        return "approvals.access"
    return None
