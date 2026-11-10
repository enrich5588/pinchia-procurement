from django.db.models import Q

from .models import ApprovalStep


def visible_approval_requests(user, queryset):
    if user.is_superuser:
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
    return (
        user.is_superuser
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
