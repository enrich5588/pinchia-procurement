from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from organization.gate import feature_required
from organization.models import Department, user_department

from .forms import (
    EquipmentApplicationForm,
    EquipmentItemFormSet,
    OfficeSupplyApplicationForm,
    OfficeSupplyItemFormSet,
)
from .models import EquipmentApplication, OfficeSupplyApplication
from .permissions import (
    can_manage_equipment_applications,
    can_manage_office_supply_applications,
)
from .services import next_equipment_case_no, next_office_supply_case_no


@login_required
def home(request):
    from .dashboard import build_dashboard

    return render(request, "procurement/home.html", build_dashboard(request.user))


@login_required
@feature_required
def supply_list(request):
    can_manage = can_manage_office_supply_applications(request.user)
    department = user_department(request.user)
    applications = OfficeSupplyApplication.objects.select_related(
        "department", "applicant", "approved_by"
    ).prefetch_related("items")
    if not can_manage:
        applications = applications.filter(applicant=request.user)
    summary = applications.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=OfficeSupplyApplication.Status.PENDING)),
        processing=Count("pk", filter=Q(status=OfficeSupplyApplication.Status.PROCESSING)),
        returned=Count("pk", filter=Q(status=OfficeSupplyApplication.Status.RETURNED)),
        closed=Count("pk", filter=Q(status__in=[
            OfficeSupplyApplication.Status.APPROVED,
            OfficeSupplyApplication.Status.CANCELLED,
        ])),
    )
    return render(request, "procurement/supply_list.html", {
        "applications": applications, "summary": summary,
        "dept": department, "can_manage": can_manage,
        "can_apply": not can_manage and department is not None,
        "departments": Department.objects.order_by("name"),
    })


@login_required
@feature_required
def supply_create(request):
    department = user_department(request.user)
    if can_manage_office_supply_applications(request.user):
        raise PermissionDenied("案件處理人員請由申請清單處理用品申請。")
    if department is None:
        raise PermissionDenied("帳號尚未設定所屬部門，無法申請用品。")
    form = OfficeSupplyApplicationForm(
        request.POST or None, department=department, applicant=request.user
    )
    formset = OfficeSupplyItemFormSet(
        request.POST or None, instance=form.instance, prefix="items"
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            application = form.save(commit=False)
            application.case_no = next_office_supply_case_no()
            application.created_by = request.user
            application.updated_by = request.user
            application.save()
            formset.instance = application
            formset.save()
        messages.success(request, f"用品申請 {application.case_no} 已送出。")
        return _modal_success_or_redirect(request)
    return _render_supply_form(
        request, form, formset, department=department, applicant=request.user,
        title="用品申請", submit_label="送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def supply_edit(request, pk):
    if can_manage_office_supply_applications(request.user):
        raise PermissionDenied("案件處理人員不可修改申請人的用品申請。")
    department = user_department(request.user)
    application = get_object_or_404(OfficeSupplyApplication, pk=pk, applicant=request.user)
    editable = {OfficeSupplyApplication.Status.PENDING, OfficeSupplyApplication.Status.RETURNED}
    if request.method == "GET" and application.status not in editable:
        raise PermissionDenied("已結案的用品申請不可修改。")
    form = OfficeSupplyApplicationForm(
        request.POST or None, instance=application,
        department=department, applicant=request.user,
    )
    formset = OfficeSupplyItemFormSet(
        request.POST or None, instance=application, prefix="items"
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            locked = get_object_or_404(
                OfficeSupplyApplication.objects.select_for_update(),
                pk=pk, applicant=request.user,
            )
            if locked.status not in editable:
                form.add_error(None, "案件狀態已變更，無法儲存本次修改。")
                return _render_supply_form(
                    request, form, formset, department=department,
                    applicant=request.user, title=f"修改申請 {locked.case_no}",
                    submit_label="重新送出申請", status=409,
                )
            locked_form = OfficeSupplyApplicationForm(
                request.POST, instance=locked, department=department, applicant=request.user
            )
            locked_formset = OfficeSupplyItemFormSet(
                request.POST, instance=locked, prefix="items"
            )
            if not locked_form.is_valid() or not locked_formset.is_valid():
                form, formset = locked_form, locked_formset
            else:
                application = locked_form.save(commit=False)
                application.status = OfficeSupplyApplication.Status.PENDING
                application.closed_at = None
                application.approved_by = None
                application.updated_by = request.user
                application.save()
                locked_formset.save()
                messages.success(request, f"用品申請 {application.case_no} 已重新送出。")
                return _modal_success_or_redirect(request)
    return _render_supply_form(
        request, form, formset, department=department, applicant=request.user,
        title=f"修改申請 {application.case_no}", submit_label="重新送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def supply_detail(request, pk):
    application = get_object_or_404(
        OfficeSupplyApplication.objects.select_related(
            "department", "applicant"
        ).prefetch_related("items"), pk=pk
    )
    if not can_manage_office_supply_applications(request.user) and application.applicant_id != request.user.pk:
        raise PermissionDenied("您無權查看此用品申請。")
    template = "procurement/_supply_detail.html" if _is_modal_request(request) else "procurement/supply_detail.html"
    return render(request, template, {
        "application": application, "is_modal": _is_modal_request(request)
    })


@login_required
@feature_required
@require_POST
def supply_return(request, pk):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可退回用品申請。")
    with transaction.atomic():
        application = get_object_or_404(OfficeSupplyApplication.objects.select_for_update(), pk=pk)
        if application.status not in {
            OfficeSupplyApplication.Status.PENDING,
            OfficeSupplyApplication.Status.PROCESSING,
        }:
            messages.error(request, "案件狀態已變更，無法退回。")
        else:
            application.status = OfficeSupplyApplication.Status.RETURNED
            application.updated_by = request.user
            application.save(update_fields=["status", "updated_by", "updated_at"])
            messages.success(request, f"用品申請 {application.case_no} 已退回。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_processing(request, pk):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可將用品申請設為處理中。")
    with transaction.atomic():
        application = get_object_or_404(OfficeSupplyApplication.objects.select_for_update(), pk=pk)
        if application.status != OfficeSupplyApplication.Status.PENDING:
            messages.error(request, "案件狀態已變更，無法開始處理。")
        else:
            application.status = OfficeSupplyApplication.Status.PROCESSING
            application.updated_by = request.user
            application.save(update_fields=["status", "updated_by", "updated_at"])
            messages.success(request, f"用品申請 {application.case_no} 已進入處理中。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_approve(request, pk):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可完成用品申請。")
    with transaction.atomic():
        application = get_object_or_404(OfficeSupplyApplication.objects.select_for_update(), pk=pk)
        if application.status not in {
            OfficeSupplyApplication.Status.PENDING,
            OfficeSupplyApplication.Status.PROCESSING,
        }:
            messages.error(request, "案件狀態已變更，無法完成。")
        else:
            application.status = OfficeSupplyApplication.Status.APPROVED
            application.closed_at = timezone.now()
            application.approved_by = request.user
            application.updated_by = request.user
            application.save(update_fields=[
                "status", "closed_at", "approved_by", "updated_by", "updated_at"
            ])
            messages.success(request, f"用品申請 {application.case_no} 已提供並結案。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_cancel(request, pk):
    if can_manage_office_supply_applications(request.user):
        raise PermissionDenied("案件處理人員不可代替申請人取消用品申請。")
    with transaction.atomic():
        application = get_object_or_404(
            OfficeSupplyApplication.objects.select_for_update(),
            pk=pk, applicant=request.user,
        )
        if application.status not in {
            OfficeSupplyApplication.Status.PENDING, OfficeSupplyApplication.Status.RETURNED
        }:
            messages.error(request, "案件狀態已變更，無法取消。")
        else:
            application.status = OfficeSupplyApplication.Status.CANCELLED
            application.closed_at = timezone.now()
            application.updated_by = request.user
            application.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
            messages.success(request, f"用品申請 {application.case_no} 已取消並結案。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_bulk_return(request):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量退回用品申請。")
    application_ids = _selected_application_ids(request.POST.getlist("application_ids"))
    if not application_ids:
        messages.error(request, "請至少勾選一筆用品申請。")
        return redirect("supplies")
    with transaction.atomic():
        applications = list(
            OfficeSupplyApplication.objects.select_for_update().filter(pk__in=application_ids)
        )
        eligible = {
            OfficeSupplyApplication.Status.PENDING,
            OfficeSupplyApplication.Status.PROCESSING,
        }
        if len(applications) != len(application_ids) or any(
            item.status not in eligible for item in applications
        ):
            messages.error(request, "部分案件狀態已變更，本次批量退回已全部取消。")
            return redirect("supplies")
        for item in applications:
            item.status = OfficeSupplyApplication.Status.RETURNED
            item.updated_by = request.user
            item.save(update_fields=["status", "updated_by", "updated_at"])
    messages.success(request, f"已批量退回 {len(applications)} 筆用品申請。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_bulk_processing(request):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量處理用品申請。")
    application_ids = _selected_application_ids(request.POST.getlist("application_ids"))
    if not application_ids:
        messages.error(request, "請至少勾選一筆用品申請。")
        return redirect("supplies")
    with transaction.atomic():
        applications = list(
            OfficeSupplyApplication.objects.select_for_update().filter(pk__in=application_ids)
        )
        eligible = {
            OfficeSupplyApplication.Status.PENDING,
            OfficeSupplyApplication.Status.PROCESSING,
        }
        if len(applications) != len(application_ids) or any(
            item.status not in eligible for item in applications
        ):
            messages.error(request, "部分案件狀態已變更，本次批量處理已全部取消。")
            return redirect("supplies")
        for item in applications:
            item.status = OfficeSupplyApplication.Status.PROCESSING
            item.updated_by = request.user
            item.save(update_fields=["status", "updated_by", "updated_at"])
    messages.success(request, f"已將 {len(applications)} 筆用品申請設為處理中。")
    return redirect("supplies")


@login_required
@feature_required
@require_POST
def supply_bulk_complete(request):
    if not can_manage_office_supply_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量完成用品申請。")
    application_ids = _selected_application_ids(request.POST.getlist("application_ids"))
    if not application_ids:
        messages.error(request, "請至少勾選一筆用品申請。")
        return redirect("supplies")
    with transaction.atomic():
        applications = list(
            OfficeSupplyApplication.objects.select_for_update().filter(pk__in=application_ids)
        )
        eligible = {
            OfficeSupplyApplication.Status.PENDING,
            OfficeSupplyApplication.Status.PROCESSING,
        }
        if len(applications) != len(application_ids) or any(
            item.status not in eligible for item in applications
        ):
            messages.error(request, "部分案件狀態已變更，本次批量完成已全部取消。")
            return redirect("supplies")
        closed_at = timezone.now()
        for item in applications:
            item.status = OfficeSupplyApplication.Status.APPROVED
            item.closed_at = closed_at
            item.approved_by = request.user
            item.updated_by = request.user
            item.save(update_fields=[
                "status", "closed_at", "approved_by", "updated_by", "updated_at"
            ])
    messages.success(request, f"已批量完成並結案 {len(applications)} 筆用品申請。")
    return redirect("supplies")


@login_required
@feature_required
def equipment_list(request):
    can_manage = can_manage_equipment_applications(request.user)
    department = user_department(request.user)
    applications = EquipmentApplication.objects.select_related(
        "department", "applicant", "approved_by"
    ).prefetch_related("items")
    if not can_manage:
        applications = applications.filter(applicant=request.user)
    summary = applications.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=EquipmentApplication.Status.PENDING)),
        processing=Count("pk", filter=Q(status=EquipmentApplication.Status.PROCESSING)),
        returned=Count("pk", filter=Q(status=EquipmentApplication.Status.RETURNED)),
        closed=Count("pk", filter=Q(status__in=[
            EquipmentApplication.Status.APPROVED,
            EquipmentApplication.Status.CANCELLED,
        ])),
    )
    applications = list(applications)
    if can_manage:
        for application in applications:
            application.can_forward_to_collaboration = application.status in {
                EquipmentApplication.Status.PENDING,
                EquipmentApplication.Status.PROCESSING,
            }
    return render(request, "procurement/equipment_list.html", {
        "applications": applications, "summary": summary,
        "dept": department, "can_manage": can_manage,
        "can_apply": not can_manage and department is not None,
        "departments": Department.objects.order_by("name"),
    })


@login_required
@feature_required
def equipment_create(request):
    department = user_department(request.user)
    if can_manage_equipment_applications(request.user):
        raise PermissionDenied("案件處理人員請由申請清單處理設備申請。")
    if department is None:
        raise PermissionDenied("帳號尚未設定所屬部門，無法申請設備。")
    form = EquipmentApplicationForm(request.POST or None, department=department, applicant=request.user)
    formset = EquipmentItemFormSet(request.POST or None, instance=form.instance, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            application = form.save(commit=False)
            application.case_no = next_equipment_case_no()
            application.created_by = request.user
            application.updated_by = request.user
            application.save()
            formset.instance = application
            formset.save()
        messages.success(request, f"設備申請 {application.case_no} 已送出。")
        return _modal_success_or_redirect(request, "equipment_procurement")
    return _render_equipment_form(
        request, form, formset, department=department, applicant=request.user,
        title="設備申請", submit_label="送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def equipment_edit(request, pk):
    if can_manage_equipment_applications(request.user):
        raise PermissionDenied("案件處理人員不可修改申請人的設備申請。")
    department = user_department(request.user)
    application = get_object_or_404(EquipmentApplication, pk=pk, applicant=request.user)
    editable = {EquipmentApplication.Status.PENDING, EquipmentApplication.Status.RETURNED}
    if request.method == "GET" and application.status not in editable:
        raise PermissionDenied("處理中或已結案的設備申請不可修改。")
    form = EquipmentApplicationForm(request.POST or None, instance=application, department=department, applicant=request.user)
    formset = EquipmentItemFormSet(request.POST or None, instance=application, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            locked = get_object_or_404(EquipmentApplication.objects.select_for_update(), pk=pk, applicant=request.user)
            if locked.status not in editable:
                form.add_error(None, "案件狀態已變更，無法儲存本次修改。")
                return _render_equipment_form(
                    request, form, formset, department=department, applicant=request.user,
                    title=f"修改申請 {locked.case_no}", submit_label="重新送出申請", status=409,
                )
            locked_form = EquipmentApplicationForm(request.POST, instance=locked, department=department, applicant=request.user)
            locked_formset = EquipmentItemFormSet(request.POST, instance=locked, prefix="items")
            if locked_form.is_valid() and locked_formset.is_valid():
                application = locked_form.save(commit=False)
                application.status = EquipmentApplication.Status.PENDING
                application.closed_at = None
                application.approved_by = None
                application.updated_by = request.user
                application.save()
                locked_formset.save()
                messages.success(request, f"設備申請 {application.case_no} 已重新送出。")
                return _modal_success_or_redirect(request, "equipment_procurement")
            form, formset = locked_form, locked_formset
    return _render_equipment_form(
        request, form, formset, department=department, applicant=request.user,
        title=f"修改申請 {application.case_no}", submit_label="重新送出申請",
        status=422 if request.method == "POST" and _is_modal_request(request) else 200,
    )


@login_required
@feature_required
def equipment_detail(request, pk):
    application = get_object_or_404(
        EquipmentApplication.objects.select_related("department", "applicant").prefetch_related("items"), pk=pk
    )
    if not can_manage_equipment_applications(request.user) and application.applicant_id != request.user.pk:
        raise PermissionDenied("您無權查看此設備申請。")
    template = "procurement/_equipment_detail.html" if _is_modal_request(request) else "procurement/equipment_detail.html"
    return render(request, template, {"application": application, "is_modal": _is_modal_request(request)})


def _equipment_manager_transition(request, pk, action):
    if not can_manage_equipment_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可處理設備申請。")
    with transaction.atomic():
        application = get_object_or_404(EquipmentApplication.objects.select_for_update(), pk=pk)
        eligible = {EquipmentApplication.Status.PENDING, EquipmentApplication.Status.PROCESSING}
        if action == "processing" and application.status != EquipmentApplication.Status.PENDING:
            messages.error(request, "案件狀態已變更，無法開始處理。")
        elif action in {"return", "complete"} and application.status not in eligible:
            messages.error(request, "案件狀態已變更，無法執行此操作。")
        else:
            if action == "processing":
                application.status = EquipmentApplication.Status.PROCESSING
                success = "已進入處理中。"
            elif action == "return":
                application.status = EquipmentApplication.Status.RETURNED
                success = "已退回。"
            else:
                application.status = EquipmentApplication.Status.APPROVED
                application.closed_at = timezone.now()
                application.approved_by = request.user
                success = "已提供並結案。"
            application.updated_by = request.user
            application.save()
            messages.success(request, f"設備申請 {application.case_no} {success}")
    return redirect("equipment_procurement")


@login_required
@feature_required
@require_POST
def equipment_processing(request, pk):
    return _equipment_manager_transition(request, pk, "processing")


@login_required
@feature_required
@require_POST
def equipment_return(request, pk):
    return _equipment_manager_transition(request, pk, "return")


@login_required
@feature_required
@require_POST
def equipment_complete(request, pk):
    if request.POST.get("asset_registration_reminder_confirmed") != "1":
        messages.error(request, "請先確認資產登記提醒，再完成設備申請。")
        return redirect("equipment_procurement")
    return _equipment_manager_transition(request, pk, "complete")


@login_required
@feature_required
@require_POST
def equipment_cancel(request, pk):
    if can_manage_equipment_applications(request.user):
        raise PermissionDenied("案件處理人員不可代替申請人取消設備申請。")
    with transaction.atomic():
        application = get_object_or_404(EquipmentApplication.objects.select_for_update(), pk=pk, applicant=request.user)
        if application.status not in {EquipmentApplication.Status.PENDING, EquipmentApplication.Status.RETURNED}:
            messages.error(request, "案件狀態已變更，無法取消。")
        else:
            application.status = EquipmentApplication.Status.CANCELLED
            application.closed_at = timezone.now()
            application.updated_by = request.user
            application.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
            messages.success(request, f"設備申請 {application.case_no} 已取消並結案。")
    return redirect("equipment_procurement")


def _equipment_bulk_transition(request, action):
    if not can_manage_equipment_applications(request.user):
        raise PermissionDenied("只有具備處理權限的人員可批量處理設備申請。")
    application_ids = _selected_application_ids(request.POST.getlist("application_ids"))
    if not application_ids:
        messages.error(request, "請至少勾選一筆設備申請。")
        return redirect("equipment_procurement")
    with transaction.atomic():
        applications = list(EquipmentApplication.objects.select_for_update().filter(pk__in=application_ids))
        eligible = {EquipmentApplication.Status.PENDING, EquipmentApplication.Status.PROCESSING}
        if len(applications) != len(application_ids) or any(item.status not in eligible for item in applications):
            messages.error(request, "部分案件狀態已變更，本次批量操作已全部取消。")
            return redirect("equipment_procurement")
        closed_at = timezone.now()
        for item in applications:
            if action == "processing":
                item.status = EquipmentApplication.Status.PROCESSING
            elif action == "return":
                item.status = EquipmentApplication.Status.RETURNED
            else:
                item.status = EquipmentApplication.Status.APPROVED
                item.closed_at = closed_at
                item.approved_by = request.user
            item.updated_by = request.user
            item.save()
    label = {"processing": "設為處理中", "return": "退回", "complete": "完成並結案"}[action]
    messages.success(request, f"已批量{label} {len(applications)} 筆設備申請。")
    return redirect("equipment_procurement")


@login_required
@feature_required
@require_POST
def equipment_bulk_processing(request):
    return _equipment_bulk_transition(request, "processing")


@login_required
@feature_required
@require_POST
def equipment_bulk_return(request):
    return _equipment_bulk_transition(request, "return")


@login_required
@feature_required
@require_POST
def equipment_bulk_complete(request):
    if request.POST.get("asset_registration_reminder_confirmed") != "1":
        messages.error(request, "請先確認資產登記提醒，再批量完成設備申請。")
        return redirect("equipment_procurement")
    return _equipment_bulk_transition(request, "complete")


def _is_modal_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _selected_application_ids(raw_ids):
    return list(dict.fromkeys(int(value) for value in raw_ids if value.isdigit()))


def _modal_success_or_redirect(request, route_name="supplies"):
    if _is_modal_request(request):
        return JsonResponse({"success": True, "redirect_url": reverse(route_name)})
    return redirect(route_name)


def _render_supply_form(request, form, formset, *, department, applicant, title, submit_label, status):
    context = {
        "form": form, "formset": formset, "department": department,
        "applicant": applicant, "form_title": title,
        "submit_label": submit_label, "form_action": request.path,
        "is_modal": _is_modal_request(request),
    }
    template = "procurement/_supply_form.html" if _is_modal_request(request) else "procurement/supply_form.html"
    return render(request, template, context, status=status)


def _render_equipment_form(request, form, formset, *, department, applicant, title, submit_label, status):
    context = {
        "form": form, "formset": formset, "department": department,
        "applicant": applicant, "form_title": title,
        "submit_label": submit_label, "form_action": request.path,
        "is_modal": _is_modal_request(request),
    }
    template = "procurement/_equipment_form.html" if _is_modal_request(request) else "procurement/equipment_form.html"
    return render(request, template, context, status=status)
