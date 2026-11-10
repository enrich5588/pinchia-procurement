from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from project_options.approvals import APPROVAL_AUTHORITY_ORDER, APPROVAL_ROUTE_RULES

from .models import ApprovalRequest, ApprovalRequestDailySequence, ApprovalStep


class ApprovalConfigurationError(ValueError):
    pass


class ApprovalStateError(ValueError):
    pass


def approver_usernames_for_amount_range(amount_range):
    try:
        return tuple(APPROVAL_ROUTE_RULES[amount_range])
    except KeyError as error:
        raise ApprovalConfigurationError("找不到適用的簽核路徑。") from error


def approval_route_for_requester(amount_range, applicant_username):
    route_usernames = approver_usernames_for_amount_range(amount_range)
    if applicant_username not in APPROVAL_AUTHORITY_ORDER:
        return route_usernames, False
    applicant_rank = APPROVAL_AUTHORITY_ORDER.index(applicant_username)
    highest_required_rank = max(
        APPROVAL_AUTHORITY_ORDER.index(username) for username in route_usernames
    )
    if applicant_rank >= highest_required_rank:
        return (), True
    return tuple(
        username for username in route_usernames
        if APPROVAL_AUTHORITY_ORDER.index(username) > applicant_rank
    ), False


def approval_route_after_return(
    amount_range, applicant_username, returned_username
):
    planned_usernames, _ = approval_route_for_requester(
        amount_range, applicant_username
    )
    if returned_username not in APPROVAL_AUTHORITY_ORDER:
        return (returned_username, *(
            username for username in planned_usernames
            if username != returned_username
        ))
    returned_rank = APPROVAL_AUTHORITY_ORDER.index(returned_username)
    return (
        returned_username,
        *(
            username for username in planned_usernames
            if APPROVAL_AUTHORITY_ORDER.index(username) > returned_rank
        ),
    )


def approvers_for_usernames(usernames):
    users = {
        user.username: user
        for user in get_user_model().objects.filter(username__in=usernames, is_active=True)
    }
    missing = [username for username in usernames if username not in users]
    if missing:
        raise ApprovalConfigurationError(
            f"簽核人帳號尚未建立或已停用：{', '.join(missing)}。"
        )
    return [users[username] for username in usernames]


def next_approval_case_no():
    sequence_date = timezone.localdate()
    sequence, _ = ApprovalRequestDailySequence.objects.select_for_update().get_or_create(
        sequence_date=sequence_date, defaults={"last_sequence": 0}
    )
    if sequence.last_sequence >= 999:
        raise ApprovalConfigurationError("今日簽呈已達 999 件上限。")
    sequence.last_sequence += 1
    sequence.save(update_fields=["last_sequence"])
    return f"{sequence_date:%y%m%d}{sequence.last_sequence:03d}"


def _create_revision_steps(*, approval, applicant, approvers, direct_approval, now):
    if direct_approval:
        ApprovalStep.objects.create(
            request=approval, round_number=approval.revision, sequence=1,
            approver=applicant, status=ApprovalStep.Status.APPROVED,
            comment="依主管簽核權限自動核准", acted_at=now,
        )
        return
    ApprovalStep.objects.bulk_create([
        ApprovalStep(
            request=approval, round_number=approval.revision,
            sequence=index, approver=approver,
            status=(ApprovalStep.Status.PENDING if index == 1 else ApprovalStep.Status.WAITING),
        )
        for index, approver in enumerate(approvers, start=1)
    ])


@transaction.atomic
def create_approval_request(
    *, applicant, department, subject, content, amount_range, document_type=""
):
    remaining_usernames, direct_approval = approval_route_for_requester(
        amount_range, applicant.username
    )
    approvers = approvers_for_usernames(remaining_usernames)
    now = timezone.now()
    request = ApprovalRequest.objects.create(
        case_no=next_approval_case_no(), subject=subject, content=content,
        amount_range=amount_range, document_type=document_type,
        department=department, applicant=applicant,
        status=(ApprovalRequest.Status.APPROVED if direct_approval else ApprovalRequest.Status.PENDING),
        current_step=1, delivered_at=now,
        closed_at=(now if direct_approval else None),
        created_by=applicant, updated_by=applicant,
    )
    _create_revision_steps(
        approval=request, applicant=applicant, approvers=approvers,
        direct_approval=direct_approval, now=now,
    )
    return request


@transaction.atomic
def resubmit_approval_request(
    *, request_id, applicant, subject, content, amount_range, document_type=""
):
    approval = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    if approval.applicant_id != applicant.pk:
        raise ApprovalStateError("只有原申請人可以修改並重送簽呈。")
    if approval.status != ApprovalRequest.Status.RETURNED:
        raise ApprovalStateError("案件狀態已變更，只有已退回案件可以修改重送。")

    returned_step = ApprovalStep.objects.select_for_update().select_related(
        "approver"
    ).filter(
        request=approval, round_number=approval.revision,
        status=ApprovalStep.Status.RETURNED,
    ).first()
    if returned_step is None:
        raise ApprovalStateError("找不到本次退回關卡，無法重新送簽。")
    remaining_usernames = approval_route_after_return(
        amount_range, applicant.username, returned_step.approver.username
    )
    direct_approval = False
    approvers = approvers_for_usernames(remaining_usernames)
    carried_steps = list(
        ApprovalStep.objects.select_for_update().select_related("approver").filter(
            request=approval, round_number=approval.revision,
            sequence__lt=returned_step.sequence,
            status=ApprovalStep.Status.APPROVED,
        )
    )
    previous_revision = approval.revision
    now = timezone.now()
    approval.subject = subject
    approval.content = content
    approval.amount_range = amount_range
    approval.document_type = document_type
    approval.revision += 1
    approval.current_step = returned_step.sequence
    approval.delivered_at = now
    approval.status = (
        ApprovalRequest.Status.APPROVED
        if direct_approval else ApprovalRequest.Status.PENDING
    )
    approval.closed_at = now if direct_approval else None
    approval.updated_by = applicant
    approval.save(update_fields=[
        "subject", "content", "amount_range", "document_type", "revision",
        "current_step", "delivered_at", "status", "closed_at",
        "updated_by", "updated_at",
    ])
    ApprovalStep.objects.bulk_create([
        ApprovalStep(
            request=approval, round_number=approval.revision,
            sequence=step.sequence, approver=step.approver,
            status=ApprovalStep.Status.APPROVED,
            comment=f"沿用第 {previous_revision} 次送簽核准結果",
            acted_at=step.acted_at,
        )
        for step in carried_steps
    ] + [
        ApprovalStep(
            request=approval, round_number=approval.revision,
            sequence=index, approver=approver,
            status=(
                ApprovalStep.Status.PENDING
                if index == returned_step.sequence
                else ApprovalStep.Status.WAITING
            ),
        )
        for index, approver in enumerate(
            approvers, start=returned_step.sequence
        )
    ])
    return approval


@transaction.atomic
def decide_approval(*, request_id, approver, approve, comment=""):
    approval = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    if approval.status != ApprovalRequest.Status.PENDING:
        raise ApprovalStateError("案件狀態已變更，無法再簽核。")
    step = ApprovalStep.objects.select_for_update().filter(
        request=approval, round_number=approval.revision,
        sequence=approval.current_step,
    ).first()
    if step is None or step.status != ApprovalStep.Status.PENDING:
        raise ApprovalStateError("目前簽核關卡不正確，請重新整理後再試。")
    if step.approver_id != approver.pk:
        raise ApprovalStateError("案件尚未輪到您簽核。")

    now = timezone.now()
    step.comment = comment.strip()
    step.acted_at = now
    approval.updated_by = approver
    if not approve:
        step.status = ApprovalStep.Status.RETURNED
        step.save(update_fields=["status", "comment", "acted_at"])
        approval.status = ApprovalRequest.Status.RETURNED
        approval.closed_at = now
        approval.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
        return approval

    step.status = ApprovalStep.Status.APPROVED
    step.save(update_fields=["status", "comment", "acted_at"])
    next_step = ApprovalStep.objects.select_for_update().filter(
        request=approval, round_number=approval.revision,
        sequence=step.sequence + 1,
    ).first()
    if next_step:
        next_step.status = ApprovalStep.Status.PENDING
        next_step.save(update_fields=["status"])
        approval.current_step = next_step.sequence
        approval.delivered_at = now
        approval.save(update_fields=[
            "current_step", "delivered_at", "updated_by", "updated_at"
        ])
    else:
        approval.status = ApprovalRequest.Status.APPROVED
        approval.closed_at = now
        approval.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
    return approval


@transaction.atomic
def withdraw_approval(*, request_id, applicant):
    approval = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    if approval.applicant_id != applicant.pk:
        raise ApprovalStateError("只有申請人可以撤回簽呈。")
    if approval.status != ApprovalRequest.Status.PENDING:
        raise ApprovalStateError("案件已結案，無法撤回。")
    approval.status = ApprovalRequest.Status.WITHDRAWN
    approval.closed_at = timezone.now()
    approval.updated_by = applicant
    approval.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
    return approval
