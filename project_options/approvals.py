from django.db import models


class ApprovalRequestStatus(models.TextChoices):
    PENDING = "pending", "簽核中"
    APPROVED = "approved", "已核准"
    RETURNED = "returned", "已退回"
    WITHDRAWN = "withdrawn", "已撤回"


class ApprovalStepStatus(models.TextChoices):
    WAITING = "waiting", "等待前一關"
    PENDING = "pending", "待簽核"
    APPROVED = "approved", "已核准"
    RETURNED = "returned", "已退回"


class ApprovalAmountRange(models.TextChoices):
    UP_TO_10000 = "up_to_10000", "10,000 元以下"
    FROM_10001_TO_20000 = "10001_to_20000", "10,001～20,000 元"
    FROM_20001_TO_40000 = "20001_to_40000", "20,001～40,000 元"
    FROM_40001 = "from_40001", "40,001 元以上"


class ApprovalDocumentType(models.TextChoices):
    ORDINARY = "ordinary", "普通件公文（8 小時內完成）"
    CONFIDENTIAL = "confidential", "密件公文（4 小時內完成）"
    URGENT = "urgent", "急件公文（2 小時內完成）"


# username 是送簽當下解析的簽核人帳號；建立後會把實際使用者凍結在 ApprovalStep。
APPROVAL_ROUTE_RULES = {
    ApprovalAmountRange.UP_TO_10000: ("wang",),
    ApprovalAmountRange.FROM_10001_TO_20000: ("wang", "kao"),
    ApprovalAmountRange.FROM_20001_TO_40000: ("wang", "kao", "gardine"),
    ApprovalAmountRange.FROM_40001: ("wang", "kao", "gardine", "hu"),
}

# 由低至高的簽核權限順序。主管建立簽呈時，只需送交自己之上的主管。
APPROVAL_AUTHORITY_ORDER = ("wang", "kao", "gardine", "hu")

# 待簽核清單排序；數字越小越優先。
APPROVAL_DOCUMENT_PRIORITY = {
    ApprovalDocumentType.URGENT: 0,
    ApprovalDocumentType.CONFIDENTIAL: 1,
    ApprovalDocumentType.ORDINARY: 2,
    "": 3,
}
