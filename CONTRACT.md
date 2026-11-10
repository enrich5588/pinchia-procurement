# 獨立專案開發原則

本專案已由「主平台功能替身」重建為獨立 Django 專案。原先僅允許修改 procurement、禁止修改平台替身與共用介面的限制，不再適用。原契約存於 [歷史整合契約](docs/legacy-integration-contract.md)，僅供追溯。

- `config/`、`organization/`、`templates/` 與四個業務 app 均為本專案可維護的原始碼。
- 共用部門與帳號請依賴 `organization`；`platform_stub`、`stubsite` 僅保留舊路徑相容性，不再擴充。
- 保留既有 app label、資料表、migration 歷史及網址。資料結構變更需新增 migration，不修改已套用的歷史 migration。
- 修改資料使用 POST；權限在後端驗證；拒絕操作須給出明確訊息。
- 確認操作使用站內 UI，不使用瀏覽器原生 confirm、alert、prompt。
- 新功能及權限邊界需有測試。交付前執行完整測試及 `makemigrations --check --dry-run`。
- 密碼、`.env`、資料庫與私有附件不得提交。部署與對外發布依使用者授權進行。
