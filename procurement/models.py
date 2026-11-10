"""辦公用品採購 —— 你的資料模型從這裡開始。

現況只有示範用的最小模型;正式規格在 SPEC.md(一張單大家填/狀態機/逐列簽收)。
建議做法:先讀懂 SPEC,自己設計 model,再對照 SPEC §6 的「現行欄位參考」檢查
有沒有漏掉的業務欄位 —— 先自己想再對答案,比直接抄學得多。
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organization.models import Department, user_department
from project_options.procurement import (
    OfficeSupplyApplicationStatus,
    OfficeSupplyProduct,
    SupplyRequestStatus,
    SUPPLY_REQUEST_STATUS_ORDER,
)


class SupplyRequest(models.Model):
    """示範起點:一張收單單(表頭)。欄位刻意不完整 —— 補齊它是你的第一個任務。"""

    Status = SupplyRequestStatus

    # 狀態的唯一順序來源(SPEC §3:狀態只能往前,倒退要擋)
    ORDER = SUPPLY_REQUEST_STATUS_ORDER

    record_no = models.CharField("紀錄編號", max_length=20, unique=True)
    filled_on = models.DateField("開單日期")
    department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                   null=True, blank=True, verbose_name="承辦單位")
    status = models.CharField("狀態", max_length=12, choices=Status.choices,
                              default=Status.OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   verbose_name="開單人")
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        verbose_name = verbose_name_plural = "用品收單單"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.record_no}({self.get_status_display()})"


class DepartmentManager(models.Model):
    """採購功能內的部門主管指派；不修改平台 UserProfile。"""

    department = models.OneToOneField(
        Department,
        on_delete=models.PROTECT,
        related_name="procurement_manager_assignment",
        verbose_name="部門",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="procurement_manager_assignment",
        verbose_name="主管",
    )
    assigned_at = models.DateTimeField("指派時間", auto_now_add=True)

    class Meta:
        verbose_name = "部門主管"
        verbose_name_plural = "部門主管"

    def __str__(self):
        return f"{self.department}主管：{self.user.username}"

    def clean(self):
        super().clean()
        if user_department(self.user) != self.department:
            raise ValidationError({"user": "主管帳號必須隸屬於所指派的部門。"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


def is_department_manager(user):
    """判斷使用者是否為其所屬部門的主管；無部門時一律回 False。"""
    if not getattr(user, "is_authenticated", False):
        return False
    department = user_department(user)
    if department is None:
        return False
    return DepartmentManager.objects.filter(
        user=user, department=department
    ).exists()


class OfficeSupplyApplicationDailySequence(models.Model):
    sequence_date = models.DateField("日期", unique=True)
    last_sequence = models.PositiveSmallIntegerField("最後流水號", default=0)

    class Meta:
        verbose_name = "用品申請每日流水號"
        verbose_name_plural = "用品申請每日流水號"


class OfficeSupplyApplication(models.Model):
    Status = OfficeSupplyApplicationStatus

    case_no = models.CharField("案件編號", max_length=9, unique=True, editable=False)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="office_supply_applications", verbose_name="申請部門",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="office_supply_applications", verbose_name="申請人",
    )
    need_date = models.DateField("需求日期")
    notes = models.TextField("備註", blank=True)
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.PENDING
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_office_supply_applications", verbose_name="建立者",
    )
    created_at = models.DateTimeField("建立日期", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="updated_office_supply_applications", verbose_name="最後修改者",
    )
    updated_at = models.DateTimeField("修改日期", auto_now=True)
    closed_at = models.DateTimeField("結案日期", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approved_office_supply_applications", verbose_name="核准人員",
    )

    class Meta:
        verbose_name = "辦公用品申請"
        verbose_name_plural = "辦公用品申請"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.case_no} {self.applicant.username}"

    def save(self, *args, **kwargs):
        if self.updated_by_id is None and self.created_by_id is not None:
            self.updated_by_id = self.created_by_id
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.applicant_id and user_department(self.applicant) != self.department:
            raise ValidationError({"applicant": "申請人必須屬於申請部門。"})


class OfficeSupplyApplicationItem(models.Model):
    Product = OfficeSupplyProduct

    application = models.ForeignKey(
        OfficeSupplyApplication, on_delete=models.CASCADE,
        related_name="items", verbose_name="用品申請",
    )
    product = models.CharField("物品名稱", max_length=30, choices=Product.choices)
    custom_name = models.CharField("自訂物品名稱", max_length=100, blank=True)
    quantity = models.PositiveIntegerField("數量")

    class Meta:
        verbose_name = "用品申請項目"
        verbose_name_plural = "用品申請項目"
        ordering = ["pk"]

    @property
    def display_name(self):
        return self.custom_name if self.product == self.Product.OTHER else self.get_product_display()

    def clean(self):
        super().clean()
        self.custom_name = self.custom_name.strip()
        if self.product == self.Product.OTHER and not self.custom_name:
            raise ValidationError({"custom_name": "選擇其他時，請填寫物品名稱。"})
        if self.product != self.Product.OTHER:
            self.custom_name = ""


class EquipmentApplicationDailySequence(models.Model):
    sequence_date = models.DateField("日期", unique=True)
    last_sequence = models.PositiveSmallIntegerField("最後流水號", default=0)

    class Meta:
        verbose_name = "設備申請每日流水號"
        verbose_name_plural = "設備申請每日流水號"


class EquipmentApplication(models.Model):
    Status = OfficeSupplyApplicationStatus

    case_no = models.CharField("案件編號", max_length=9, unique=True, editable=False)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT,
        related_name="equipment_applications", verbose_name="申請部門",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="equipment_applications", verbose_name="申請人",
    )
    need_date = models.DateField("需求日期")
    notes = models.TextField("備註（需求規格等）", blank=True)
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.PENDING
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_equipment_applications", verbose_name="建立者",
    )
    created_at = models.DateTimeField("建立日期", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="updated_equipment_applications", verbose_name="最後修改者",
    )
    updated_at = models.DateTimeField("修改日期", auto_now=True)
    closed_at = models.DateTimeField("結案日期", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approved_equipment_applications", verbose_name="完成人員",
    )

    class Meta:
        verbose_name = "設備申請"
        verbose_name_plural = "設備申請"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.case_no} {self.applicant.username}"

    def save(self, *args, **kwargs):
        if self.updated_by_id is None and self.created_by_id is not None:
            self.updated_by_id = self.created_by_id
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.applicant_id and user_department(self.applicant) != self.department:
            raise ValidationError({"applicant": "申請人必須屬於申請部門。"})


class EquipmentApplicationItem(models.Model):
    application = models.ForeignKey(
        EquipmentApplication, on_delete=models.CASCADE,
        related_name="items", verbose_name="設備申請",
    )
    equipment_name = models.CharField("物品名稱", max_length=200)
    quantity = models.PositiveIntegerField("數量")

    class Meta:
        verbose_name = "設備申請項目"
        verbose_name_plural = "設備申請項目"
        ordering = ["pk"]

    def clean(self):
        super().clean()
        self.equipment_name = self.equipment_name.strip()
        if not self.equipment_name:
            raise ValidationError({"equipment_name": "請填寫物品名稱。"})
