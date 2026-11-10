from django.db import models


class AssetCategory(models.TextChoices):
    IT_EQUIPMENT = "it_equipment", "資訊設備"
    FURNITURE = "furniture", "桌椅櫃子"
    OTHER = "other", "其他"


class AssetRegistrationStatus(models.TextChoices):
    PENDING = "pending", "申請中"
    RETURNED = "returned", "退回"
    APPROVED = "approved", "已核准"
    CANCELLED = "cancelled", "取消"


# 資料庫監看頁的自動更新下拉選項：(傳入值, 顯示文字)
DATABASE_MONITOR_REFRESH_OPTIONS = (
    ("0", "關閉"),
    ("10", "每 10 秒"),
    ("15", "每 15 秒"),
    ("30", "每 30 秒"),
    ("60", "每 60 秒"),
)
DATABASE_MONITOR_DEFAULT_REFRESH = "15"
