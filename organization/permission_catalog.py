"""Stable permission codes shared by models, policies and the management UI."""
MANAGEMENT_DEPARTMENT_NAME = "管理與事業發展部"

# code, label, description, default for authenticated users
PERMISSIONS = (
    ("supplies.access", "辦公用品：進入", "查看本人案件與使用申請功能。", True),
    ("supplies.manage", "辦公用品：處理", "查看全公司用品案件、處理、完成與退回。", False),
    ("equipment.access", "設備申請：進入", "查看本人案件與使用設備申請功能。", True),
    ("equipment.manage", "設備申請：處理", "查看全公司設備案件、處理、完成與退回。", False),
    ("assets.access", "財產清冊：進入", "查看本部門財產與圖片。", True),
    ("assets.manage", "財產清冊：管理", "查看全公司財產、新增、編輯及批量匯入。", False),
    ("registrations.access", "資產登記：進入", "查看本人登記與提出申請。", True),
    ("registrations.manage", "資產登記：審核", "查看全公司登記、核准、退回及批量處理。", False),
    ("collaboration.access", "協作案件：進入", "查看及處理交給本部門的案件。", True),
    ("collaboration.manage", "協作案件：統籌", "查看全公司協作案件、轉發需求與撤回。", False),
    ("approvals.access", "數位簽呈：進入", "提出簽呈、查看本人或本人參與簽核的案件。", True),
    ("approvals.view_all", "數位簽呈：全公司閱覽", "查看全公司簽呈，不包含代替他人簽核。", False),
    ("database.monitor", "資料庫：唯讀監看", "查看資料表、欄位及完整業務資料；不含修改。", False),
)
PERMISSION_CHOICES = [(code, label) for code, label, _, _ in PERMISSIONS]
DEFAULTS = {code: default for code, _, _, default in PERMISSIONS}
MANAGEMENT_GRANTS = (
    "supplies.manage", "equipment.manage", "assets.manage", "registrations.manage",
    "collaboration.manage", "database.monitor",
)
