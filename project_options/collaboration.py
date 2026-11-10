from django.db import models


class CollaborationTaskStatus(models.TextChoices):
    PENDING = "pending", "待處理"
    PROCESSING = "processing", "處理中"
    COMPLETED = "completed", "已完成"
    RETURNED = "returned", "已退回"
    WITHDRAWN = "withdrawn", "已撤回"


class CollaborationSourceForm(models.TextChoices):
    EQUIPMENT_APPLICATION = "equipment_application", "設備申請"
