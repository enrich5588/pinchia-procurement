"""Role-aware counts for the work overview. Uses the same visibility rules as each list."""

from django.urls import reverse
from django.utils import timezone

from approval_hub.models import ApprovalRequest
from approval_hub.permissions import visible_approval_requests
from assets.models import AssetRegistration
from assets.permissions import can_manage_assets, can_manage_registrations
from collaboration_hub.models import CollaborationTask
from collaboration_hub.permissions import can_manage_collaboration_tasks
from organization.models import user_department
from organization.permissions import has_permission
from project_options.approvals import APPROVAL_DOCUMENT_PRIORITY

from .models import EquipmentApplication, OfficeSupplyApplication
from .permissions import (
    can_manage_equipment_applications,
    can_manage_office_supply_applications,
)

DOCUMENT_SHORT = {
    "urgent": "急件",
    "confidential": "密件",
    "ordinary": "普通件",
}


def _greeting(now):
    if now.hour < 11:
        return "早安"
    if now.hour < 18:
        return "午安"
    return "晚安"


def build_dashboard(user):
    department = user_department(user)
    manage_procurement = can_manage_office_supply_applications(user)
    manage_assets = can_manage_assets(user)
    manage_registrations = can_manage_registrations(user)
    manage_equipment = can_manage_equipment_applications(user)
    manage_collaboration = can_manage_collaboration_tasks(user)
    scope = "全公司 · 處理人員檢視" if manage_procurement else "我的案件"
    equipment_scope = "全公司 · 處理人員檢視" if manage_equipment else "我的案件"
    asset_scope = "全公司 · 處理人員檢視" if manage_registrations else "我的申請"

    supplies = OfficeSupplyApplication.objects.all()
    equipment = EquipmentApplication.objects.all()
    if not manage_procurement:
        supplies = supplies.filter(applicant=user)
    if not manage_equipment:
        equipment = equipment.filter(applicant=user)
    registrations = AssetRegistration.objects.all()
    if not manage_registrations:
        registrations = registrations.filter(applicant=user)
    approvals = visible_approval_requests(user, ApprovalRequest.objects.all())
    tasks = CollaborationTask.objects.select_related("assigned_department")
    if not manage_collaboration:
        tasks = tasks.filter(assigned_department=department) if department else tasks.none()
    if not has_permission(user, "supplies.access"):
        supplies = supplies.none()
    if not has_permission(user, "equipment.access"):
        equipment = equipment.none()
    if not has_permission(user, "registrations.access"):
        registrations = registrations.none()
    if not has_permission(user, "collaboration.access"):
        tasks = tasks.none()

    supply_pending = supplies.filter(status=OfficeSupplyApplication.Status.PENDING).count()
    equipment_processing = equipment.filter(
        status=EquipmentApplication.Status.PROCESSING
    ).count()
    registration_pending = registrations.filter(
        status=AssetRegistration.Status.PENDING
    ).count()
    approval_pending_qs = approvals.filter(status=ApprovalRequest.Status.PENDING)
    approval_pending = approval_pending_qs.count()

    priority = list(
        approval_pending_qs.select_related("department", "applicant").order_by("delivered_at")[:12]
    )
    priority.sort(key=lambda item: (
        APPROVAL_DOCUMENT_PRIORITY.get(item.document_type, 3),
        item.delivered_at or item.created_at,
        item.pk,
    ))
    for item in priority:
        item.document_short = DOCUMENT_SHORT.get(item.document_type, "未標示")

    activities = []
    for item in supplies.order_by("-updated_at")[:4]:
        activities.append({
            "when": item.updated_at,
            "text": f"辦公用品申請 {item.case_no} {item.get_status_display()}",
            "url": reverse("supply_detail", args=[item.pk]),
            "kind": "supply",
        })
    for item in equipment.order_by("-updated_at")[:4]:
        activities.append({
            "when": item.updated_at,
            "text": f"設備申請 {item.case_no} {item.get_status_display()}",
            "url": reverse("equipment_detail", args=[item.pk]),
            "kind": "equipment",
        })
    for item in registrations.order_by("-modified_at")[:4]:
        activities.append({
            "when": item.modified_at,
            "text": f"資產登記 {item.case_no} {item.get_status_display()}",
            "url": reverse("registration_detail", args=[item.pk]),
            "kind": "registration",
        })
    for item in tasks.order_by("-updated_at")[:4]:
        activities.append({
            "when": item.updated_at,
            "text": f"{item.assigned_department.name}協作案件 {item.case_no} {item.get_status_display()}",
            "url": reverse("collaboration_task_detail", args=[item.pk]),
            "kind": "collaboration",
        })
    for item in approvals.order_by("-updated_at")[:4]:
        activities.append({
            "when": item.updated_at,
            "text": f"簽呈 {item.case_no} {item.get_status_display()}",
            "url": reverse("approval_detail", args=[item.pk]),
            "kind": "approval",
        })
    activities.sort(key=lambda item: item["when"], reverse=True)

    parts = []
    if approval_pending:
        parts.append(f"{approval_pending} 筆簽呈正在簽核")
    if equipment_processing:
        parts.append(f"{equipment_processing} 筆設備申請需要安排")
    if parts:
        hero_text = "目前有 " + "，另有 ".join(parts) + "。從這裡，開始今天的工作。"
    else:
        hero_text = "目前沒有待簽核的案件，也沒有處理中的設備申請。可以從下方開始新的工作。"

    return {
        "dept": department,
        "greeting": _greeting(timezone.localtime()),
        "display_name": (user.get_full_name() or "").strip() or user.get_username(),
        "hero_text": hero_text,
        "scope": scope,
        "equipment_scope": equipment_scope,
        "asset_scope": asset_scope,
        "supply_pending": supply_pending,
        "equipment_processing": equipment_processing,
        "registration_pending": registration_pending,
        "approval_pending": approval_pending,
        "priority_approvals": priority[:5],
        "activities": activities[:5],
        "can_apply": has_permission(user, "supplies.access") and not manage_procurement and department is not None,
        "can_apply_equipment": has_permission(user, "equipment.access") and not manage_equipment and department is not None,
        "can_manage_equipment": manage_equipment,
        "can_manage": manage_procurement,
        "can_apply_registration": has_permission(user, "registrations.access") and not manage_registrations and department is not None,
        "can_manage_registrations": manage_registrations,
        "can_manage_assets": manage_assets,
        "can_create_approval": has_permission(user, "approvals.access") and department is not None,
    }
