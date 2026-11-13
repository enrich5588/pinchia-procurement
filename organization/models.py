from organization.audit_models import AuditedModel
"""Shared organization models, preserving the existing database schema."""
from django.conf import settings
from django.db import models
from .permission_catalog import PERMISSION_CHOICES


class Department(AuditedModel):
    """共用部門。"""
    name = models.CharField("名稱", max_length=100, unique=True)

    class Meta:
        verbose_name = verbose_name_plural = "部門"

    def __str__(self):
        return self.name


class DepartmentSyncState(models.Model):
    """Singleton checkpoint/lease for the M365 directory synchronization worker."""
    last_success = models.DateTimeField("上次成功", null=True, blank=True)
    next_attempt = models.DateTimeField("下次嘗試", null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField("同步狀態", max_length=300, blank=True)
    department_count = models.PositiveIntegerField("M365 部門數", default=0)
    employee_count = models.PositiveIntegerField("M365 員工數", default=0)

    class Meta:
        verbose_name = verbose_name_plural = "M365 組織同步狀態"


class UserProfile(AuditedModel):
    """使用者的部門歸屬；管理員可沒有 profile，請以 user_department 取得部門。"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="profile")
    department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                   verbose_name="部門")

    class Meta:
        verbose_name = verbose_name_plural = "使用者部門"

    def __str__(self):
        return f"{self.user.username} @ {self.department}"


class MicrosoftIdentity(AuditedModel):
    """Stable Entra identity; email and UPN are display metadata, never link keys."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="microsoft_identity", verbose_name="本機帳號",
    )
    tenant_id = models.UUIDField("Tenant ID")
    object_id = models.UUIDField("Object ID")
    principal_name = models.CharField("M365 登入名稱", max_length=320, blank=True)
    department_name = models.CharField("Graph 部門", max_length=100, blank=True)
    last_synced_at = models.DateTimeField("最後同步時間", null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "M365 帳號綁定"
        constraints = [models.UniqueConstraint(
            fields=["tenant_id", "object_id"], name="unique_microsoft_tenant_object",
        )]

    def __str__(self):
        return f"{self.user} ({self.object_id})"


class PermissionRule(AuditedModel):
    class Effect(models.TextChoices):
        ALLOW = "allow", "允許"
        DENY = "deny", "拒絕"

    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="permission_rules", verbose_name="部門")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="permission_rules", verbose_name="個人")
    permission = models.CharField("權限", max_length=64, choices=PERMISSION_CHOICES)
    effect = models.CharField("設定", max_length=5, choices=Effect.choices)

    class Meta:
        verbose_name = verbose_name_plural = "部門與個人權限規則"
        constraints = [
            models.CheckConstraint(condition=(
                models.Q(department__isnull=False, user__isnull=True)
                | models.Q(department__isnull=True, user__isnull=False)
            ), name="permission_rule_exactly_one_target"),
            models.CheckConstraint(condition=models.Q(effect__in=["allow", "deny"]),
                                   name="permission_rule_valid_effect"),
            models.UniqueConstraint(fields=["department", "permission"], name="unique_department_permission"),
            models.UniqueConstraint(fields=["user", "permission"], name="unique_user_permission"),
        ]


class FeaturePanel(AuditedModel):
    class Status(models.TextChoices):
        DEVELOPING = "developing", "開發中"
        READY = "ready", "已完成・暫不開放"
        OPEN = "open", "已完成・已開放"

    code = models.CharField("面板代碼", max_length=32, unique=True)
    status = models.CharField("開放狀態", max_length=12, choices=Status.choices, default=Status.DEVELOPING)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField("最後更新", auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "功能面板"
        constraints = [models.CheckConstraint(condition=models.Q(status__in=["developing", "ready", "open"]),
                                              name="feature_panel_valid_status")]


class PermissionAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                              related_name="permission_audits")
    actor_label = models.CharField("設定人員", max_length=150)
    target_type = models.CharField("對象類型", max_length=10)
    target_id = models.PositiveBigIntegerField("對象 ID")
    target_label = models.CharField("對象名稱", max_length=200)
    changes = models.JSONField("異動內容", default=dict)
    created_at = models.DateTimeField("異動時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = verbose_name_plural = "權限異動紀錄"


def user_department(user):
    """取使用者部門;沒有 profile 回 None。**用這個,不要直接摸 user.profile**。"""
    profile = getattr(user, "profile", None)
    return profile.department if profile else None


class OperationLog(models.Model):
    ACTIONS = [('request','查閱／請求'),('create','新增'),('update','修改'),('delete','刪除'),
               ('login','登入'),('logout','登出'),('login_failed','登入失敗'),('background','背景作業')]
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actor_label = models.CharField('操作者', max_length=150)
    action = models.CharField('操作', max_length=20, choices=ACTIONS)
    source = models.CharField('來源', max_length=80)
    request_id = models.UUIDField('關聯編號', db_index=True)
    model_label = models.CharField('資料類型', max_length=150, blank=True)
    object_id = models.CharField('資料編號', max_length=100, blank=True)
    object_label = models.CharField('資料名稱', max_length=200, blank=True)
    changes = models.JSONField('修改內容', default=dict)
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField('路徑', max_length=500, blank=True)
    route = models.CharField(max_length=150, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField('結果', max_length=30, blank=True)
    created_at = models.DateTimeField('時間', auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at','-pk']
        verbose_name = verbose_name_plural = '操作紀錄'
