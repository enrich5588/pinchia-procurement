from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from organization.gate import feature_required
from organization.models import user_department
from project_options.approvals import APPROVAL_DOCUMENT_PRIORITY

from .forms import ApprovalDecisionForm, ApprovalRequestForm
from .models import ApprovalRequest, ApprovalStep
from .permissions import can_view_approval_request, visible_approval_requests
from .services import (
    ApprovalConfigurationError,
    ApprovalStateError,
    approval_route_after_return,
    approval_route_for_requester,
    create_approval_request,
    decide_approval,
    resubmit_approval_request,
    withdraw_approval,
)


def _is_modal_request(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _base_queryset():
    return ApprovalRequest.objects.select_related(
        "department", "applicant", "created_by", "updated_by"
    ).prefetch_related("steps__approver")


@login_required
@feature_required
def approval_list(request):
    approvals = visible_approval_requests(request.user, _base_queryset())
    summary = approvals.aggregate(
        total=Count("pk", distinct=True),
        pending=Count("pk", filter=Q(status=ApprovalRequest.Status.PENDING), distinct=True),
        approved=Count("pk", filter=Q(status=ApprovalRequest.Status.APPROVED), distinct=True),
        returned=Count("pk", filter=Q(status=ApprovalRequest.Status.RETURNED), distinct=True),
        withdrawn=Count("pk", filter=Q(status=ApprovalRequest.Status.WITHDRAWN), distinct=True),
    )
    approvals = list(approvals)
    awaiting_me = 0
    for approval in approvals:
        steps = [
            step for step in approval.steps.all()
            if step.round_number == approval.revision
        ]
        approval.route_names = " → ".join(step.approver.username for step in steps)
        approval.progress_total = len(steps)
        approval.progress_done = sum(
            step.status == ApprovalStep.Status.APPROVED for step in steps
        )
        approval.progress_percent = round(
            approval.progress_done / approval.progress_total * 100
        ) if approval.progress_total else 0
        current = next((step for step in steps if step.sequence == approval.current_step), None)
        approval.current_approver = current.approver if current and approval.status == ApprovalRequest.Status.PENDING else None
        approval.can_act = bool(
            current and current.status == ApprovalStep.Status.PENDING
            and current.approver_id == request.user.pk
            and approval.status == ApprovalRequest.Status.PENDING
        )
        approval.can_withdraw = (
            approval.applicant_id == request.user.pk
            and approval.status == ApprovalRequest.Status.PENDING
        )
        approval.can_resubmit = (
            approval.applicant_id == request.user.pk
            and approval.status == ApprovalRequest.Status.RETURNED
        )
        if approval.can_act:
            awaiting_me += 1
    status_priority = {
        ApprovalRequest.Status.PENDING: 0,
        ApprovalRequest.Status.APPROVED: 1,
        ApprovalRequest.Status.RETURNED: 2,
        ApprovalRequest.Status.WITHDRAWN: 3,
    }
    approvals.sort(key=lambda approval: (
        status_priority[approval.status],
        APPROVAL_DOCUMENT_PRIORITY.get(approval.document_type, 3)
        if approval.status == ApprovalRequest.Status.PENDING else 0,
        approval.delivered_at.timestamp()
        if approval.status == ApprovalRequest.Status.PENDING
        else -approval.updated_at.timestamp(),
        approval.pk,
    ))
    return render(request, "approval_hub/approval_list.html", {
        "approvals": approvals, "summary": summary, "awaiting_me": awaiting_me,
        "department": user_department(request.user),
    })


@login_required
@feature_required
def approval_create(request):
    department = user_department(request.user)
    if department is None:
        raise PermissionDenied("帳號尚未設定所屬部門，無法建立簽呈。")
    form = ApprovalRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            approval = create_approval_request(
                applicant=request.user, department=department, **form.cleaned_data
            )
        except ApprovalConfigurationError as error:
            form.add_error(None, str(error))
        else:
            if approval.status == ApprovalRequest.Status.APPROVED:
                messages.success(
                    request,
                    f"簽呈 {approval.case_no} 在您的簽核權限內，已自動核准。",
                )
            else:
                first_approver = approval.steps.select_related("approver").get(
                    round_number=approval.revision, sequence=1
                ).approver
                messages.success(
                    request,
                    f"簽呈 {approval.case_no} 已送出，現由 {first_approver.username} 簽核。",
                )
            if _is_modal_request(request):
                return JsonResponse({"success": True, "redirect_url": reverse("approval_list")})
            return redirect("approval_list")
    template = "approval_hub/_approval_form.html" if _is_modal_request(request) else "approval_hub/approval_form.html"
    return render(request, template, {
        "form": form, "department": department, "form_action": request.path,
        "route_rules": _route_rules_for_user(request.user.username),
        "form_eyebrow": "NEW APPROVAL", "form_title": "建立數位簽呈",
        "form_description": "送出後即凍結簽核路徑；若被退回，可修改後重新送簽。",
        "submit_label": "送出簽呈",
    }, status=422 if request.method == "POST" and _is_modal_request(request) else 200)


@login_required
@feature_required
def approval_resubmit(request, pk):
    approval = get_object_or_404(_base_queryset(), pk=pk)
    if approval.applicant_id != request.user.pk:
        raise PermissionDenied("只有原申請人可以修改並重送簽呈。")
    if request.method == "GET" and approval.status != ApprovalRequest.Status.RETURNED:
        raise PermissionDenied("只有已退回案件可以修改並重送。")
    returned_step = approval.steps.filter(
        round_number=approval.revision, status=ApprovalStep.Status.RETURNED
    ).select_related("approver").first()
    if returned_step is None:
        raise PermissionDenied("找不到本次退回關卡，無法重新送簽。")
    carried_usernames = list(approval.steps.filter(
        round_number=approval.revision,
        sequence__lt=returned_step.sequence,
        status=ApprovalStep.Status.APPROVED,
    ).order_by("sequence").values_list("approver__username", flat=True))
    form = ApprovalRequestForm(request.POST or None, instance=approval)
    conflict = False
    if request.method == "POST" and form.is_valid():
        try:
            approval = resubmit_approval_request(
                request_id=approval.pk, applicant=request.user,
                subject=form.cleaned_data["subject"],
                content=form.cleaned_data["content"],
                amount_range=form.cleaned_data["amount_range"],
                document_type=form.cleaned_data["document_type"],
            )
        except (ApprovalConfigurationError, ApprovalStateError) as error:
            form.add_error(None, str(error))
            conflict = isinstance(error, ApprovalStateError)
        else:
            if approval.status == ApprovalRequest.Status.APPROVED:
                message = f"簽呈 {approval.case_no} 修改後在您的權限內，已自動核准。"
            else:
                first = approval.steps.select_related("approver").get(
                    round_number=approval.revision, sequence=1
                )
                message = f"簽呈 {approval.case_no} 已修改並重新送交 {first.approver.username} 簽核。"
            messages.success(request, message)
            if _is_modal_request(request):
                return JsonResponse({"success": True, "redirect_url": reverse("approval_list")})
            return redirect("approval_list")
    template = "approval_hub/_approval_form.html" if _is_modal_request(request) else "approval_hub/approval_form.html"
    status = 409 if conflict else (422 if request.method == "POST" and _is_modal_request(request) else 200)
    return render(request, template, {
        "form": form, "department": approval.department,
        "form_action": request.path,
        "route_rules": _route_rules_for_user(
            request.user.username, returned_step.approver.username,
            carried_usernames,
        ),
        "form_eyebrow": f"RESUBMIT · VERSION {approval.revision + 1}",
        "form_title": "修改並重送簽呈",
        "form_description": f"沿用案件編號 {approval.case_no}，原退回紀錄會完整保留。",
        "submit_label": "修改並重新送簽",
    }, status=status)


@login_required
@feature_required
def approval_detail(request, pk):
    approval = get_object_or_404(_base_queryset(), pk=pk)
    if not can_view_approval_request(request.user, approval):
        raise PermissionDenied("您無權查看此簽呈。")
    all_steps = list(approval.steps.all())
    current_steps = [
        step for step in all_steps if step.round_number == approval.revision
    ]
    progress_done = sum(
        step.status == ApprovalStep.Status.APPROVED for step in current_steps
    )
    progress_total = len(current_steps)
    current = next((
        step for step in current_steps if step.sequence == approval.current_step
    ), None)
    can_act = bool(
        current and current.approver_id == request.user.pk
        and current.status == ApprovalStep.Status.PENDING
        and approval.status == ApprovalRequest.Status.PENDING
    )
    template = "approval_hub/_approval_detail.html" if _is_modal_request(request) else "approval_hub/approval_detail.html"
    return render(request, template, {
        "approval": approval, "steps": all_steps, "can_act": can_act,
        "progress_done": progress_done, "progress_total": progress_total,
        "progress_percent": round(progress_done / progress_total * 100) if progress_total else 0,
        "can_withdraw": approval.applicant_id == request.user.pk and approval.status == ApprovalRequest.Status.PENDING,
        "can_resubmit": approval.applicant_id == request.user.pk and approval.status == ApprovalRequest.Status.RETURNED,
    })


def _route_rules_for_user(
    username, returned_username=None, carried_usernames=()
):
    return [
        _route_rule_for_user(
            value, label, username, returned_username, carried_usernames
        )
        for value, label in ApprovalRequest.AmountRange.choices
    ]


def _route_rule_for_user(
    value, label, username, returned_username=None, carried_usernames=()
):
    if returned_username:
        remaining_approvers = approval_route_after_return(
            value, username, returned_username
        )
        approvers = (*carried_usernames, *remaining_approvers)
        direct_approval = False
        route = " → ".join([
            *(f"{name}（已核准）" for name in carried_usernames),
            *remaining_approvers,
        ])
    else:
        approvers, direct_approval = approval_route_for_requester(value, username)
        route = "依主管權限自動核准" if direct_approval else " → ".join(approvers)
    return {
        "value": value,
        "label": label,
        "approvers": list(approvers),
        "route": route,
    }


def _decision(request, pk, *, approve):
    if request.method == "GET" and not _is_modal_request(request):
        return redirect("approval_list")
    approval = get_object_or_404(_base_queryset(), pk=pk)
    current = next((
        step for step in approval.steps.all()
        if step.round_number == approval.revision
        and step.sequence == approval.current_step
    ), None)
    if (
        approval.status != ApprovalRequest.Status.PENDING
        or not current
        or current.status != ApprovalStep.Status.PENDING
        or current.approver_id != request.user.pk
    ):
        raise PermissionDenied("案件尚未輪到您簽核。")
    form = ApprovalDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            decide_approval(
                request_id=approval.pk, approver=request.user, approve=approve,
                comment=form.cleaned_data["comment"],
            )
        except ApprovalStateError as error:
            form.add_error(None, str(error))
        else:
            action = "核准" if approve else "退回"
            messages.success(request, f"簽呈 {approval.case_no} 已{action}。")
            if _is_modal_request(request):
                return JsonResponse({"success": True, "redirect_url": reverse("approval_list")})
            return redirect("approval_list")
    template = "approval_hub/_decision_form.html" if _is_modal_request(request) else "approval_hub/decision_form.html"
    return render(request, template, {
        "form": form, "approval": approval, "approve": approve,
        "form_action": request.path,
    }, status=409 if form.non_field_errors() else (422 if request.method == "POST" and _is_modal_request(request) else 200))


@login_required
@feature_required
def approval_approve(request, pk):
    return _decision(request, pk, approve=True)


@login_required
@feature_required
def approval_return(request, pk):
    return _decision(request, pk, approve=False)


@login_required
@feature_required
@require_POST
def approval_withdraw(request, pk):
    approval = get_object_or_404(ApprovalRequest, pk=pk)
    if approval.applicant_id != request.user.pk:
        raise PermissionDenied("只有申請人可以撤回簽呈。")
    try:
        approval = withdraw_approval(request_id=approval.pk, applicant=request.user)
    except ApprovalStateError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"簽呈 {approval.case_no} 已撤回。")
    return redirect("approval_list")
