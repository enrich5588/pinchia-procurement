from organization.audit_models import AuditedModel
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from organization.models import Department
from project_options.collaboration import CollaborationSourceForm, CollaborationTaskStatus


class CollaborationTaskDailySequence(models.Model):
    sequence_date = models.DateField("日期", unique=True)
    last_sequence = models.PositiveSmallIntegerField("最後流水號", default=0)

    class Meta:
        verbose_name = "協作案件每日流水號"
        verbose_name_plural = "協作案件每日流水號"


class CollaborationTask(AuditedModel):
    Status = CollaborationTaskStatus
    SourceForm = CollaborationSourceForm

    case_no = models.CharField("協作案件編號", max_length=9, unique=True, editable=False)
    assigned_department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="collaboration_tasks", verbose_name="承接部門",
    )
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.PENDING,
    )
    source_form = models.CharField("來源表單", max_length=40, choices=SourceForm.choices)
    source_case_no = models.CharField("來源案件編號", max_length=40)
    source_content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, verbose_name="來源資料類型",
    )
    source_object_id = models.PositiveBigIntegerField("來源資料 ID")
    source_object = GenericForeignKey("source_content_type", "source_object_id")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_collaboration_tasks", verbose_name="轉發人員",
    )
    created_at = models.DateTimeField("建立日期", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="updated_collaboration_tasks", verbose_name="最後修改者",
    )
    updated_at = models.DateTimeField("修改日期", auto_now=True)
    closed_at = models.DateTimeField("完成日期", null=True, blank=True)
    return_reason = models.TextField("退回原因", blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="returned_collaboration_tasks", verbose_name="退回人員",
    )
    returned_at = models.DateTimeField("退回日期", null=True, blank=True)

    class Meta:
        verbose_name = "協作案件"
        verbose_name_plural = "協作案件"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_content_type", "source_object_id"],
                condition=~models.Q(status=CollaborationTaskStatus.WITHDRAWN),
                name="unique_active_collaboration_source_object",
            ),
        ]
        indexes = [
            models.Index(fields=["assigned_department", "status"]),
            models.Index(fields=["source_form", "source_case_no"]),
        ]

    def __str__(self):
        return f"{self.case_no} / {self.get_source_form_display()} {self.source_case_no}"
