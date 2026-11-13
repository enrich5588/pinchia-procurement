# 品嘉採購與資產管理系統

獨立 Django 專案，保留現有介面與流程，無須依賴主平台原始碼。技術維持 Django 5.2.5、SQLite、Django Templates、原生 JavaScript/CSS、Pillow 與 openpyxl。框架版本維持既有版本；登入已改用公司 M365，部門由 Graph user.department 同步。

## Windows 快速啟動

需要 Python 3.12 或 3.13（本次驗證使用 3.12.13）。在專案根目錄執行：

```powershell
./scripts/setup.ps1
./scripts/dev.ps1
```

開啟 http://127.0.0.1:8000/ 。登入頁預設使用公司 M365；需先完成 [M365 設定與既有帳號綁定](docs/m365-login.md)。未設定公司參數時會顯示設定提示，密碼登入預設關閉。既有資料庫與帳號會沿用。全新環境若需要示範資料，明確加上 `./scripts/setup.ps1 -Demo`；會建立 demo 密碼帳號、部門主管與簽核人（wang／kao／gardine／hu），僅供開發使用。不要對正式資料執行此選項。

指定 Python：`./scripts/setup.ps1 -Python 'C:/path/to/python.exe'`。重建環境位於 `.venv-rebuild/`，原 `.venv/` 保留。腳本安裝 `requirements.lock`、建立 `.env`（存在則保留）、執行 migration 與系統檢查；開發伺服器啟動時不會隱性修改資料庫。

## macOS / Linux

```sh
python3 -m venv .venv-rebuild
.venv-rebuild/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv-rebuild/bin/python manage.py migrate
.venv-rebuild/bin/python manage.py runserver
```

## 目錄與維護邊界

| 目錄 | 職責 |
| --- | --- |
| `config/` | URL、WSGI/ASGI、開發與正式環境設定 |
| `organization/` | 部門、使用者部門關聯、功能開關、示範帳號 |
| `templates/` | 專案共用版面、登入畫面 |
| `procurement/` | 辦公用品與設備申請 |
| `assets/` | 財產清冊、資產登記、圖片、Excel 匯入與資料庫監看 |
| `collaboration_hub/` | 協作轉發、承接、退回與完成 |
| `approval_hub/` | 數位簽呈、簽核、退回、撤回與重新送簽 |
| `project_options/` | 集中選項與狀態 |
| `platform_stub/`、`stubsite/` | 歷史匯入路徑相容層 |

上述程式皆由本專案維護，舊主平台唯讀限制已解除，詳見 [開發原則](CONTRACT.md)。既有業務模板、CSS、JavaScript 與命名網址皆沿用；共用模板現由 `templates/` 優先載入。

## 設定與資料

複製 `.env.example` 為 `.env`；系統環境變數優先。`.env` 僅支援 `KEY=value`、整行註解與成對引號，不展開變數或行內註解。

- M365 環境變數、憑證、回呼網址與權限請見 [M365 登入說明](docs/m365-login.md)。
- 部門與個人權限、預設值及管理方式請見 [權限管理說明](docs/PERMISSIONS.md)。
- 各功能開發與開放狀態，請見 [面板管理說明](docs/PANELS.md)。
- 操作歷程、修改前後值及 30 天保存設定，請見 [操作紀錄說明](docs/OPERATION-LOGS.md)。
- 財產 Excel 批量上傳及依財產編號覆蓋規則，請見 [匯入說明](docs/asset-import.md)。
- M365 全公司部門與員工定期同步請見 [組織同步說明](docs/m365-directory-sync.md)；需要 Application `User.Read.All` 及管理員同意。
- `FEATURE_OPEN_TO_ALL`：預設 true，false 時僅超級使用者可進入受控功能。
- `DJANGO_ALLOWED_HOSTS`：逗號分隔的主機名稱。
- `DJANGO_DB_PATH`：SQLite 絕對路徑；預設根目錄 `db.sqlite3`。
- `DJANGO_MEDIA_ROOT`：私有檔案根目錄；預設 `private-media/`。資產圖片仍經權限驗證的 view 提供，不公開整個資料夾。
- `DJANGO_CSRF_TRUSTED_ORIGINS`：部署時使用的 HTTPS origin。

組織模組名稱改為 `organization`，但刻意保留 `platform_stub` app label、資料表名稱、content type 與 migration 身分，避免既有外鍵、資料與權限失效。不要手動重新命名資料表或刪除 migration。

升級前備份資料庫與 `private-media/`。請在停止寫入或使用 SQLite backup API 的情況下備份資料庫。還原時需讓程式版本、資料庫與附件對應。詳細驗證方式與範圍見 [重建說明](docs/environment-rebuild.md)。

## 驗證

```powershell
./scripts/test.ps1
./.venv-rebuild/Scripts/python.exe manage.py check
./.venv-rebuild/Scripts/python.exe manage.py makemigrations --check --dry-run
./.venv-rebuild/Scripts/python.exe -m pip check
```

## 部署

Linux VM 的 `main` 自動部署設定已提供，包含 GitHub Actions、Docker、HTTPS、資料備份與 migration；首次安裝及啟用步驟請見 [自動部署說明](docs/auto-deploy.md)。

正式環境在程序環境設定 `DJANGO_SETTINGS_MODULE=config.settings.production`、隨機且至少 50 字元的 `DJANGO_SECRET_KEY` 及明確的 `DJANGO_ALLOWED_HOSTS`。正式設定強制安全 cookie，預設 HTTPS redirect 與 HSTS；TLS 由部署服務提供。反向代理的 HTTPS header 信任設定需依實際部署架構調整。

提供 `config.wsgi:application` 與 `config.asgi:application` 作為正式伺服器入口，依部署環境安裝及設定 WSGI/ASGI server。`sh start-server.sh <server command ...>` 先 migration 再啟動指定命令。未傳入命令時只提供開發伺服器；正式設定會拒絕此用法。`Procfile` 仍是開發／預覽啟動入口，正式部署需覆寫命令。

部署前執行 `manage.py check --deploy` 與 `manage.py collectstatic --noinput`，將 `staticfiles/` 交給部署平台或 web server 提供。資料庫及私有附件應掛載持久化磁碟。
