from django.conf import settings
from django.db import models

from organization.models import Department
from project_options.approvals import (
    ApprovalAmountRange,
    ApprovalDocumentType,
    ApprovalRequestStatus,
    ApprovalStepStatus,
)


class ApprovalRequestDailySequence(models.Model):
    sequence_date = models.DateField("日期", unique=True)
    last_sequence = models.PositiveSmallIntegerField("最後流水號", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "簽呈每日流水號"


class ApprovalRequest(models.Model):
    Status = ApprovalRequestStatus
    AmountRange = ApprovalAmountRange
    DocumentType = ApprovalDocumentType

    case_no = models.CharField("簽呈編號", max_length=9, unique=True, editable=False)
    subject = models.CharField("簽呈主旨", max_length=200)
    content = models.TextField("簽呈內容")
    amount_range = models.CharField(
        "涉及金額", max_length=20, choices=AmountRange.choices,
        default=AmountRange.UP_TO_10000,
    )
    document_type = models.CharField(
        "公文種類", max_length=20, choices=DocumentType.choices, blank=True, default="",
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="approval_requests", verbose_name="申請部門",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="approval_requests", verbose_name="申請人",
    )
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.PENDING,
    )
    revision = models.PositiveSmallIntegerField("送簽版本", default=1)
    current_step = models.PositiveSmallIntegerField("目前關卡", default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_approval_requests", verbose_name="建立者",
    )
    created_at = models.DateTimeField("建立日期", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="updated_approval_requests", verbose_name="最後修改者",
    )
    updated_at = models.DateTimeField("修改日期", auto_now=True)
    delivered_at = models.DateTimeField("目前關卡送達時間")
    closed_at = models.DateTimeField("結案日期", null=True, blank=True)

    class Meta:
        verbose_name = "簽呈"
        verbose_name_plural = "簽呈"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["applicant", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.case_no} / {self.subject}"


class ApprovalStep(models.Model):
    Status = ApprovalStepStatus

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE,
        related_name="steps", verbose_name="簽呈",
    )
    round_number = models.PositiveSmallIntegerField("送簽版本", default=1)
    sequence = models.PositiveSmallIntegerField("簽核順序")
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="approval_steps", verbose_name="簽核人",
    )
    status = models.CharField("狀態", max_length=12, choices=Status.choices)
    comment = models.TextField("簽核意見", blank=True)
    acted_at = models.DateTimeField("簽核時間", null=True, blank=True)

    class Meta:
        verbose_name = "簽核關卡"
        verbose_name_plural = "簽核關卡"
        ordering = ["round_number", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "round_number", "sequence"],
                name="unique_approval_request_round_sequence",
            ),
        ]
        indexes = [models.Index(fields=["approver", "status"])]

    def __str__(self):
        return f"{self.request.case_no} 第 {self.sequence} 關 / {self.approver}"
