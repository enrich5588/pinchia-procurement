from django.db import models


class SupplyRequestStatus(models.TextChoices):
    OPEN = "open", "收單中"
    CLOSED = "closed", "已收單"
    PURCHASED = "purchased", "已採購"


SUPPLY_REQUEST_STATUS_ORDER = ["open", "closed", "purchased"]


class OfficeSupplyApplicationStatus(models.TextChoices):
    PENDING = "pending", "申請中"
    PROCESSING = "processing", "處理中"
    RETURNED = "returned", "退回"
    APPROVED = "approved", "已提供"
    CANCELLED = "cancelled", "取消"


class OfficeSupplyProduct(models.TextChoices):
    BALLPOINT_PEN = "ballpoint_pen", "原子筆"
    MECHANICAL_PENCIL = "mechanical_pencil", "自動鉛筆"
    PENCIL_LEAD = "pencil_lead", "自動鉛筆芯"
    ERASER = "eraser", "橡皮擦"
    RULER_15 = "ruler_15", "尺(15cm)"
    RULER_30_METAL = "ruler_30_metal", "尺(30cm鐵尺)"
    STAPLER = "stapler", "釘書機"
    STAPLES = "staples", "訂書針(盒)"
    PAPER_CLIP_SMALL = "paper_clip_small", "小迴紋針(盒)"
    PAPER_CLIP_LARGE = "paper_clip_large", "大迴紋針(盒)"
    TAPE = "tape", "膠帶"
    PACKING_TAPE = "packing_tape", "封箱膠帶"
    TAPE_DISPENSER = "tape_dispenser", "膠帶台"
    PACKING_TAPE_DISPENSER = "packing_tape_dispenser", "封箱膠帶台"
    L_FOLDER = "l_folder", "L夾"
    OTHER = "other", "其他"
