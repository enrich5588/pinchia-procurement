from django.db.models import Q

from .models import ApprovalStep
from organization.permissions import has_permission


def visible_approval_requests(user, queryset):
    if not has_permission(user, "approvals.access"):
        return queryset.none()
    if has_permission(user, "approvals.view_all"):
        return queryset
    return queryset.filter(
        Q(applicant=user)
        | Q(steps__approver=user, steps__status__in=[
            ApprovalStep.Status.PENDING,
            ApprovalStep.Status.APPROVED,
            ApprovalStep.Status.RETURNED,
        ])
    ).distinct()


def can_view_approval_request(user, approval):
    if not has_permission(user, "approvals.access"):
        return False
    return (
        has_permission(user, "approvals.view_all")
        or approval.applicant_id == user.pk
        or approval.steps.filter(
            approver=user,
            status__in=[
                ApprovalStep.Status.PENDING,
                ApprovalStep.Status.APPROVED,
                ApprovalStep.Status.RETURNED,
            ],
        ).exists()
    )
