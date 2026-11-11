from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from organization.gate import feature_required
from organization.models import Department, user_department
from procurement.models import EquipmentApplication

from .forms import CollaborationReturnForm, EquipmentForwardForm
from .models import CollaborationTask
from .permissions import can_manage_collaboration_tasks, can_view_collaboration_task
from .services import next_collaboration_case_no


@login_required
@feature_required
def task_list(request):
    department = user_department(request.user)
    can_manage = can_manage_collaboration_tasks(request.user)
    tasks = CollaborationTask.objects.select_related(
        "assigned_department", "created_by", "updated_by", "source_content_type"
    )
    if not can_manage:
        if department is None:
            tasks = tasks.none()
        else:
            tasks = tasks.filter(assigned_department=department)
    summary = tasks.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=CollaborationTask.Status.PENDING)),
        processing=Count("pk", filter=Q(status=CollaborationTask.Status.PROCESSING)),
        completed=Count("pk", filter=Q(status=CollaborationTask.Status.COMPLETED)),
        returned=Count("pk", filter=Q(status=CollaborationTask.Status.RETURNED)),
        withdrawn=Count("pk", filter=Q(status=CollaborationTask.Status.WITHDRAWN)),
    )
    tasks = list(tasks)
    for task in tasks:
        _set_task_capabilities(request.user, task, can_manage=can_manage, department=department)
    return render(request, "collaboration_hub/task_list.html", {
        "tasks": tasks, "summary": summary, "department": department,
        "can_manage": can_manage,
        "departments": Department.objects.order_by("name"),
    })


@login_required
@feature_required
def task_detail(request, pk):
    task = get_object_or_404(
        CollaborationTask.objects.select_related(
            "assigned_department", "created_by", "updated_by", "source_content_type"
        ), pk=pk,
    )
    if not can_view_collaboration_task(request.user, task):
        raise PermissionDenied("您無權查看此協作案件。")
    source_application = None
    source_missing = False
    if task.source_form == CollaborationTask.SourceForm.EQUIPMENT_APPLICATION:
        source_application = EquipmentApplication.objects.select_related(
            "department", "applicant"
        ).prefetch_related("items").filter(
            pk=task.source_object_id, case_no=task.source_case_no
        ).first()
        source_missing = source_application is None
    template = "collaboration_hub/_task_detail_content.html" if _is_modal_request(request) else "collaboration_hub/task_detail.html"
    return render(request, template, {
        "task": task, "source_application": source_application,
        "source_missing": source_missing, "is_modal": _is_modal_request(request),
    })


@login_required
@feature_required
@require_POST
def task_processing(request, pk):
    with transaction.atomic():
        task = get_object_or_404(
            CollaborationTask.objects.select_for_update().select_related("assigned_department"),
            pk=pk,
        )
        _require_receiving_department(request.user, task)
        if task.status != CollaborationTask.Status.PENDING:
            messages.error(request, "案件狀態已變更，無法開始處理。")
        else:
            task.status = CollaborationTask.Status.PROCESSING
            task.updated_by = request.user
            task.save(update_fields=["status", "updated_by", "updated_at"])
            messages.success(request, f"協作案件 {task.case_no} 已進入處理中。")
    return redirect("collaboration_task_list")


@login_required
@feature_required
@require_POST
def task_complete(request, pk):
    with transaction.atomic():
        task = get_object_or_404(
            CollaborationTask.objects.select_for_update().select_related("assigned_department"),
            pk=pk,
        )
        _require_receiving_department(request.user, task)
        if task.status not in {
            CollaborationTask.Status.PENDING,
            CollaborationTask.Status.PROCESSING,
        }:
            messages.error(request, "案件狀態已變更，無法完成。")
        else:
            task.status = CollaborationTask.Status.COMPLETED
            task.closed_at = timezone.now()
            task.updated_by = request.user
            task.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
            messages.success(request, f"協作案件 {task.case_no} 已完成。")
    return redirect("collaboration_task_list")


@login_required
@feature_required
def task_return(request, pk):
    task = get_object_or_404(
        CollaborationTask.objects.select_related("assigned_department"), pk=pk
    )
    _require_receiving_department(request.user, task)
    form = CollaborationReturnForm(request.POST or None)
    eligible = {CollaborationTask.Status.PENDING, CollaborationTask.Status.PROCESSING}
    if request.method == "GET" and task.status not in eligible:
        raise PermissionDenied("此協作案件目前不可退回。")
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = get_object_or_404(
                CollaborationTask.objects.select_for_update().select_related("assigned_department"),
                pk=pk,
            )
            _require_receiving_department(request.user, locked)
            if locked.status not in eligible:
                form.add_error(None, "案件狀態已變更，無法退回。")
                task = locked
            else:
                locked.status = CollaborationTask.Status.RETURNED
                locked.return_reason = form.cleaned_data["return_reason"].strip()
                locked.returned_by = request.user
                locked.returned_at = timezone.now()
                locked.closed_at = None
                locked.updated_by = request.user
                locked.save(update_fields=[
                    "status", "return_reason", "returned_by", "returned_at",
                    "closed_at", "updated_by", "updated_at",
                ])
                messages.success(request, f"協作案件 {locked.case_no} 已退回發送方。")
                if _is_modal_request(request):
                    return JsonResponse({
                        "success": True,
                        "redirect_url": reverse("collaboration_task_list"),
                    })
                return redirect("collaboration_task_list")
    status = 409 if request.method == "POST" and form.non_field_errors() else (
        422 if request.method == "POST" and _is_modal_request(request) else 200
    )
    return _render_return_form(request, form, task, status=status)


@login_required
@feature_required
@require_POST
def task_withdraw(request, pk):
    if not can_manage_collaboration_tasks(request.user):
        raise PermissionDenied("只有發送方可撤回協作案件。")
    with transaction.atomic():
        task = get_object_or_404(CollaborationTask.objects.select_for_update(), pk=pk)
        if task.status not in {
            CollaborationTask.Status.PENDING,
            CollaborationTask.Status.RETURNED,
        }:
            messages.error(request, "案件已由承接部門處理或結案，無法撤回。")
        else:
            task.status = CollaborationTask.Status.WITHDRAWN
            task.closed_at = timezone.now()
            task.updated_by = request.user
            task.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
            messages.success(request, f"協作案件 {task.case_no} 已撤回。")
    return redirect("collaboration_task_list")


@login_required
@feature_required
def forward_equipment(request, pk):
    if not can_manage_collaboration_tasks(request.user):
        raise PermissionDenied("只有具備處理權限的人員可轉發設備申請。")
    application = get_object_or_404(
        EquipmentApplication.objects.select_related("department", "applicant"), pk=pk
    )
    info_department = Department.objects.filter(name="資訊部").first()
    form = EquipmentForwardForm(
        request.POST or None,
        initial={"assigned_department": info_department} if request.method == "GET" else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked = get_object_or_404(
                    EquipmentApplication.objects.select_for_update(), pk=pk
                )
                if locked.status not in {
                    EquipmentApplication.Status.PENDING,
                    EquipmentApplication.Status.PROCESSING,
                }:
                    form.add_error(None, "案件狀態已變更，無法轉發。")
                else:
                    content_type = ContentType.objects.get_for_model(EquipmentApplication)
                    if CollaborationTask.objects.filter(
                        source_content_type=content_type, source_object_id=locked.pk,
                    ).exclude(
                        status=CollaborationTask.Status.WITHDRAWN,
                    ).exists():
                        form.add_error(None, "此設備申請已有尚未撤回的協作案件，不可重複轉發。")
                    else:
                        task = CollaborationTask.objects.create(
                            case_no=next_collaboration_case_no(),
                            assigned_department=form.cleaned_data["assigned_department"],
                            source_form=CollaborationTask.SourceForm.EQUIPMENT_APPLICATION,
                            source_case_no=locked.case_no,
                            source_content_type=content_type,
                            source_object_id=locked.pk,
                            created_by=request.user,
                            updated_by=request.user,
                        )
                        locked.status = EquipmentApplication.Status.PROCESSING
                        locked.updated_by = request.user
                        locked.save(update_fields=["status", "updated_by", "updated_at"])
        except IntegrityError:
            form.add_error(None, "此設備申請已有尚未撤回的協作案件，不可重複轉發。")
        if not form.errors:
            messages.success(
                request,
                f"設備申請 {application.case_no} 已轉發為協作案件 {task.case_no}。",
            )
            if _is_modal_request(request):
                return JsonResponse({
                    "success": True,
                    "redirect_url": reverse("equipment_procurement"),
                })
            return redirect("equipment_procurement")
    status = 422 if request.method == "POST" and _is_modal_request(request) else 200
    template = "collaboration_hub/_equipment_forward_form.html" if _is_modal_request(request) else "collaboration_hub/equipment_forward_form.html"
    return render(request, template, {
        "form": form, "application": application,
        "form_action": request.path, "is_modal": _is_modal_request(request),
    }, status=status)


def _is_modal_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _set_task_capabilities(user, task, *, can_manage, department):
    is_receiver = department is not None and task.assigned_department_id == department.pk
    task.can_withdraw = can_manage and task.status in {
        CollaborationTask.Status.PENDING,
        CollaborationTask.Status.RETURNED,
    }
    task.can_start_processing = is_receiver and task.status == CollaborationTask.Status.PENDING
    task.can_complete = is_receiver and task.status in {
        CollaborationTask.Status.PENDING,
        CollaborationTask.Status.PROCESSING,
    }
    task.can_return = task.can_complete


def _require_receiving_department(user, task):
    department = user_department(user)
    if department is None or task.assigned_department_id != department.pk:
        raise PermissionDenied("只有承接部門人員可處理此協作案件。")


def _render_return_form(request, form, task, *, status):
    template = "collaboration_hub/_return_form.html" if _is_modal_request(request) else "collaboration_hub/return_form.html"
    return render(request, template, {
        "form": form, "task": task, "form_action": request.path,
        "is_modal": _is_modal_request(request),
    }, status=status)
