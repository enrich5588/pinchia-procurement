# 專案環境重建紀錄

日期：2026-11-09。採用現有 Django 技術架構，在本 repository 原地建立獨立可維護的專案，沿用現有業務程式與資料。

## 架構變更

- 新增 `config.settings.base`、`development`、`production`，分離環境責任；新入口為 `config.urls`、`config.wsgi`、`config.asgi`。
- 建立 `organization` 作為共用帳號／部門 app。業務模組與測試統一引用新路徑。保留舊 app label `platform_stub` 與歷史 migration 身分，以維持資料及權限相容。
- 共用版面與登入模板改由專案根目錄 `templates/` 管理。四個業務模組的模板、JavaScript、CSS 及路由完整沿用。
- 建立獨立 `.venv-rebuild`，以 `requirements.lock` 固定含間接依賴的完整版本；保留原 `.venv`。
- 提供 Windows 初始化、開發啟動與測試腳本；開發啟動不再自動執行 migration。初始化／部署腳本明確執行 migration。
- 以 `.env`／程序環境管理路徑、主機及功能開關；正式設定要求有效 secret 與明確主機，並啟用 HTTPS 相關設定。
- 原整合契約封存至 `docs/legacy-integration-contract.md`，現行 `CONTRACT.md` 改為獨立專案維護原則。

## 功能移植範圍

| 模組 | 保留內容 |
| --- | --- |
| 採購 | 辦公用品、設備申請、編輯、退回、處理、完成、取消、批次操作 |
| 資產 | 財產清冊、登記、修訂、圖片權限、Excel 匯入預覽與範本、批次核准、資料庫監看 |
| 協作 | 案件清單、設備轉發、承接與完成、退回、撤回 |
| 簽核 | 簽呈建立、明細、簽核、退回、撤回、重新送簽及歷程 |
| 共用 | 登入／登出、首頁、部門／使用者、管理後台、功能開關 |

沿用現有功能邏輯與權限，不改寫現有資料表。沒有實作新的 SSO：目前仍是 Django 帳號登入，原專案中的 MS365 說明並非已存在的串接。

## 驗證結果

新環境完整測試：179 項全部通過（含後續瀏覽器檢查的修正測試）。系統檢查、正式部署設定檢查、依賴一致性、migration 差異檢查、靜態資源收集與 HTTP 啟動檢查皆通過。

## 驗證方式

- 以新虛擬環境執行所有原有回歸測試，新增組織模型舊路徑相容、主頁面與前端資源、登入模板、功能開關、環境解析及正式設定反例測試。
- `manage.py check`、`makemigrations --check --dry-run`、`pip check` 與 `git diff --check`。
- 以範例正式設定執行 `check --deploy --fail-level WARNING`；檢查不需部署或連線到外部服務。
- `collectstatic --noinput` 驗證靜態資源可收集。
- 既有 SQLite 資料庫透過 backup API 建立快照與驗證副本；在副本執行 migration 前後逐表比對全部資料列，確認一致。
- 另建空白資料庫，完成所有 migration、示範帳號與主管帳號建立，確認全新初始化可用。
- 實際啟動 HTTP 開發伺服器，確認登入頁與四個模組的代表性 JavaScript 回應 200，完成後關閉驗證伺服器。

已完成後續瀏覽器逐頁檢查、主要流程操作與版面修正，詳見 [瀏覽器驗證紀錄](browser-verification.md)，其中列出各頁涵蓋範圍與原生選檔步驟的工具限制。實際正式主機、網域、TLS、SSO 與 WSGI/ASGI server 仍依部署環境設定，本次沒有對外部署。

資料庫快照位於本機 `backups/environment-rebuild/`，驗證副本位於 `.rebuild-verification/`，皆不進版控；私有附件沿用 `private-media/` 原路徑。

## 日常操作

```powershell
./scripts/dev.ps1
./scripts/test.ps1
```

修改依賴時同步更新 `requirements.txt`（直接依賴）與 `requirements.lock`（完整鎖定版本），於乾淨環境安裝並重新驗證。不要直接修改歷史 migration、重新命名舊表，或將私有媒體當作公開 static 提供。
