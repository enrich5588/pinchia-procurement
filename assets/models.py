from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from organization.models import Department, user_department
from project_options.assets import AssetCategory, AssetRegistrationStatus
from .storage import asset_image_path, asset_image_storage, asset_import_path


class AssetCompany(models.TextChoices):
    PINJIA_DEVELOPMENT = "品嘉建設", "品嘉建設"
    PINJIA_CONSTRUCTION = "品嘉營造", "品嘉營造"
    PINJIA_ASSET = "品佳資產", "品佳資產"
    VENDOR_EQUIPMENT = "廠商設備", "廠商設備"
    OTHER = "其他", "其他"


def calculate_asset_total(unit_price, business_tax):
    return Decimal(str(unit_price or 0)) + Decimal(str(business_tax or 0))


class Asset(models.Model):
    Company = AssetCompany
    Category = AssetCategory

    asset_no = models.CharField("財產編號", max_length=50, unique=True)
    name = models.CharField("財產名稱", max_length=200)
    company = models.CharField(
        "公司", max_length=20, choices=Company.choices,
        default=Company.PINJIA_DEVELOPMENT,
    )
    category = models.CharField("財產類別", max_length=100)
    brand = models.CharField("廠牌", max_length=100, blank=True)
    specification = models.CharField("財產規格型號", max_length=255, blank=True)
    accessories = models.TextField("配件", blank=True)
    quantity = models.PositiveIntegerField(
        "數量", default=1, validators=[MinValueValidator(1)]
    )
    unit_price = models.DecimalField(
        "單價", max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    business_tax = models.DecimalField(
        "營業稅", max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    total = models.DecimalField(
        "合計", max_digits=13, decimal_places=2, default=0, editable=False
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="assets", verbose_name="所屬部門"
    )
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assets_in_custody",
        null=True,
        blank=True,
        verbose_name="保管人員",
    )
    purchase_date = models.DateField("採購日期")
    useful_life_years = models.PositiveSmallIntegerField(
        "使用年限（年）", null=True, blank=True
    )
    notes = models.TextField("備註（保固期限等）", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assets",
        verbose_name="建立者",
    )
    created_at = models.DateTimeField("建立日期", auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_assets",
        verbose_name="最後修改者",
    )
    updated_at = models.DateTimeField("修改日期", auto_now=True)

    class Meta:
        verbose_name = "公司財產"
        verbose_name_plural = "公司財產"
        ordering = ["department__name", "asset_no"]

    def __str__(self):
        return f"{self.asset_no} {self.name}"

    def save(self, *args, **kwargs):
        if self.updated_by_id is None and self.created_by_id is not None:
            self.updated_by_id = self.created_by_id
        self.total = calculate_asset_total(self.unit_price, self.business_tax)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.custodian and user_department(self.custodian) != self.department:
            raise ValidationError({"custodian": "保管人員必須屬於財產的所屬部門。"})


class AssetImage(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="images", null=True, blank=True)
    registration = models.ForeignKey(
        "AssetRegistration", on_delete=models.SET_NULL, related_name="images", null=True, blank=True,
    )
    image = models.ImageField("圖片", storage=asset_image_storage, upload_to=asset_image_path)
    uploaded_at = models.DateTimeField("上傳時間", auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "財產圖片"
        verbose_name_plural = "財產圖片"


class AssetImportBatch(models.Model):
    class ImportType(models.TextChoices):
        ASSET = "asset", "財產清冊"
        REGISTRATION = "registration", "資產登記"

    import_type = models.CharField(
        "匯入類型", max_length=20, choices=ImportType.choices,
        default=ImportType.ASSET,
    )
    source_file = models.FileField(
        "Excel 暫存檔", storage=asset_image_storage, upload_to=asset_import_path
    )
    source_filename = models.CharField("原始檔名", max_length=255)
    rows = models.JSONField("預覽資料", default=list)
    skipped = models.JSONField("跳過資料", default=list)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="asset_import_batches", verbose_name="建立者",
    )
    created_at = models.DateTimeField("建立時間", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "財產批量匯入暫存"
        verbose_name_plural = "財產批量匯入暫存"


class AssetRegistrationDailySequence(models.Model):
    sequence_date = models.DateField("日期", unique=True)
    last_sequence = models.PositiveSmallIntegerField("最後流水號", default=0)

    class Meta:
        verbose_name = "資產登記每日流水號"
        verbose_name_plural = "資產登記每日流水號"


class AssetRegistration(models.Model):
    Status = AssetRegistrationStatus
    Company = AssetCompany

    case_no = models.CharField("案件編號", max_length=9, unique=True, editable=False)
    name = models.CharField("財產名稱", max_length=200)
    company = models.CharField(
        "公司", max_length=20, choices=Company.choices,
        default=Company.PINJIA_DEVELOPMENT,
    )
    category = models.CharField("財產類別", max_length=100)
    brand = models.CharField("廠牌", max_length=100, blank=True)
    specification = models.CharField("財產規格型號", max_length=255, blank=True)
    accessories = models.TextField("配件", blank=True)
    quantity = models.PositiveIntegerField(
        "數量", default=1, validators=[MinValueValidator(1)]
    )
    unit_price = models.DecimalField(
        "單價", max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    business_tax = models.DecimalField(
        "營業稅", max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    total = models.DecimalField(
        "合計", max_digits=13, decimal_places=2, default=0, editable=False
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="asset_registrations",
        verbose_name="所屬部門",
    )
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="asset_registration_custody", verbose_name="保管人員",
        null=True, blank=True,
    )
    purchase_date = models.DateField("採購日期")
    useful_life_years = models.PositiveSmallIntegerField(
        "使用年限（年）", null=True, blank=True
    )
    notes = models.TextField("備註（保固期限等）", blank=True)
    status = models.CharField(
        "狀態", max_length=12, choices=Status.choices, default=Status.PENDING
    )
    applied_at = models.DateTimeField("申請日期", auto_now_add=True)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="asset_registrations", verbose_name="申請人",
    )
    modified_at = models.DateTimeField("修改日期", auto_now=True)
    closed_at = models.DateTimeField("結案日期", null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approved_asset_registrations", verbose_name="核准人員",
    )
    asset = models.OneToOneField(
        Asset, on_delete=models.PROTECT, null=True, blank=True,
        related_name="registration", verbose_name="建立的公司財產",
    )
    target_asset = models.ForeignKey(
        Asset, on_delete=models.PROTECT, null=True, blank=True,
        related_name="revision_registrations", verbose_name="異動的公司財產",
    )
    asset_images_to_remove = models.ManyToManyField(
        AssetImage, blank=True, related_name="removal_requests",
        verbose_name="核准後移除的財產圖片",
    )

    class Meta:
        verbose_name = "資產登記申請"
        verbose_name_plural = "資產登記申請"
        ordering = ["-applied_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_asset"],
                condition=models.Q(
                    target_asset__isnull=False,
                    status__in=[
                        AssetRegistrationStatus.PENDING,
                        AssetRegistrationStatus.RETURNED,
                    ],
                ),
                name="unique_active_asset_revision",
            ),
        ]

    def __str__(self):
        return f"{self.case_no} {self.name}"

    def save(self, *args, **kwargs):
        self.total = calculate_asset_total(self.unit_price, self.business_tax)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.custodian_id and user_department(self.custodian) != self.department:
            raise ValidationError({"custodian": "保管人員必須屬於所選部門。"})
