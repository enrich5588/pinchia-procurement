"""Release gates sit above department and individual permissions."""
from django.conf import settings

PANELS = (
    ("supplies", "辦公用品申請", "用品需求申請、審核與處理", "pen"),
    ("equipment", "設備申請", "設備需求、採購與轉發", "screen"),
    ("assets", "財產清冊", "公司財產查詢、編輯與匯入", "box"),
    ("registrations", "資產登記", "資產新增、異動與登記審核", "file"),
    ("collaboration", "協作案件", "跨部門需求轉發與承接", "users"),
    ("approvals", "數位簽呈", "簽呈申請、簽核與閱覽", "check"),
)
PANEL_KEYS = {code for code, *_ in PANELS}


def panel_available(user, code):
    if not user.is_authenticated or not user.is_active or code not in PANEL_KEYS:
        return False
    if user.is_superuser:
        return True
    if not settings.FEATURE_OPEN_TO_ALL:
        return False
    from .models import FeaturePanel
    return FeaturePanel.objects.filter(code=code, status=FeaturePanel.Status.OPEN).exists()
