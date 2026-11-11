"""Shared navigation context for the redesigned application shell."""

from django.contrib.staticfiles import finders
from django.utils import timezone

WEEKDAYS = "一二三四五六日"


def _section(url_name):
    if url_name == "panel_management":
        return "panels"
    if url_name == "permission_management":
        return "permissions"
    if url_name == "home":
        return "overview"
    if url_name in {"supplies"} or url_name.startswith("supply"):
        return "supplies"
    if url_name.startswith("equipment"):
        return "equipment"
    if url_name.startswith("registration"):
        return "registrations"
    if url_name.startswith("asset"):
        return "assets"
    if url_name.startswith("collaboration"):
        return "collaboration"
    if url_name.startswith("approval"):
        return "approvals"
    if url_name == "database_monitor":
        return "monitor"
    return ""


def _pending_approvals(user):
    from approval_hub.models import ApprovalRequest
    from approval_hub.permissions import visible_approval_requests

    queryset = visible_approval_requests(
        user, ApprovalRequest.objects.filter(status=ApprovalRequest.Status.PENDING)
    )
    return queryset.count()


def shell_context(request):
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else ""
    section = _section(url_name or "")
    now = timezone.localtime()
    user = getattr(request, "user", None)
    authenticated = bool(user and user.is_authenticated)
    department = None
    display_name = ""
    initial = ""
    pending = 0
    if authenticated:
        from organization.models import user_department

        department = user_department(user)
        display_name = (user.get_full_name() or "").strip() or user.get_username()
        first = display_name[:1]
        initial = first.upper() if first.isascii() else first
        pending = _pending_approvals(user)
    access = {}
    if authenticated:
        from organization.permissions import has_permission
        access = {key: has_permission(user, f"{key}.access") for key in [
            "supplies", "equipment", "assets", "registrations", "collaboration", "approvals",
        ]}
    mobile = ""
    if section == "overview":
        mobile = "overview"
    elif section in {"supplies", "equipment"}:
        mobile = "apply"
    elif section in {"assets", "registrations"}:
        mobile = "assets"
    elif section == "approvals":
        mobile = "approvals"
    labels = {
        "overview": "工作總覽",
        "supplies": "採購申請",
        "equipment": "採購申請",
        "assets": "資產管理",
        "registrations": "資產管理",
        "collaboration": "協作專區",
        "approvals": "簽核管理",
        "monitor": "系統管理",
        "permissions": "權限管理",
        "panels": "面板管理",
    }
    return {"shell": {
        "section": section,
        "access": access,
        "section_label": labels.get(section, "工作總覽"),
        "mobile": mobile,
        "today": f"{now.year} 年 {now.month} 月 {now.day} 日 · 週{WEEKDAYS[now.weekday()]}（台北時間）",
        "display_name": display_name,
        "initial": initial,
        "department": department.name if department else "",
        "pending_approvals": pending,
        "logo_white": bool(finders.find("brand/logo-white.png")),
        "logo_full": bool(finders.find("brand/logo-full.png")),
        "authenticated": authenticated,
    }}
