# M365 部門與員工自動同步

系統從 Microsoft Graph `/v1.0/users` 讀取公司成員的 Object ID、名稱、UPN、mail、department 及 accountEnabled。完整讀取所有分頁後，才在同一交易更新部門與員工，失敗不寫入半份清單。只納入 `userType=Member`，空部門略過，部門名稱去除首尾空白並去重。未曾登入的員工也會出現在「權限管理 → 個人權限」選單。

## 公司端授權

在現有 Entra App registration：

1. 進入 API permissions → Add a permission → Microsoft Graph。
2. 選 **Application permissions**，新增 **User.Read.All**。
3. 由租用戶管理員執行 **Grant admin consent**，確認狀態已授權。

登入原有的 Delegated `User.Read` 保留。同步使用現有 Server 憑證／Client secret 與 `https://graph.microsoft.com/.default` 應用程式權杖，不需要新增密鑰、回呼網址或讓每位員工個別同意。僅有 Delegated `User.Read.All` 不足以供背景服務執行。

官方參考：[List users](https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0)、[分頁處理](https://learn.microsoft.com/en-us/graph/paging)。

## 自動執行

`.env` 選用設定（不填時使用下列預設）：

```dotenv
M365_DEPARTMENT_SYNC_ENABLED=true
M365_DEPARTMENT_SYNC_SECONDS=21600
```

背景服務啟動時檢查是否到期，首次立即同步，成功後每六小時更新；授權、網路或限流失敗十五分鐘後重試。兩個設定同時控制部門與員工。`./scripts/dev.ps1` 會隨網站啟動背景服務，離開時結束該子程序。直接執行 `runserver` 不會自動啟動同步程序。

正式 Server 需由既有服務管理器持續執行以下獨立 worker，工作目錄、環境設定及資料庫須與網站相同，並設定程序失敗時重新啟動：

```powershell
./.venv-rebuild/Scripts/python.exe manage.py sync_m365_directory --watch
```

立即手動同步（不等待下次週期）：

```powershell
./.venv-rebuild/Scripts/python.exe manage.py sync_m365_directory --force
```

舊命令 `sync_m365_departments` 亦同步部門與員工。資料庫鎖與十分鐘租約避免多個 worker 同時更新，程序中斷後可恢復。管理後台「M365 組織同步狀態」可檢查最近成功時間、下次重試、部門／員工數及錯誤原因；紀錄不包含權杖或密鑰。

## 身分與資料保留

- 帳號以 Tenant ID＋Object ID 對應，姓名、UPN 或 mail 異動不會換帳號主鍵，既有個人權限、申請與簽核紀錄保留。
- 不依 mail 或相同 username 自動合併本機帳號。若有既有未綁定帳號，應先用既有 `bind_m365_user` 程序核對綁定，再同步，避免將不同身分的資料錯誤合併。
- 新員工建立無本機密碼的一般帳號；部門權限依同步後所屬部門生效，個人明確設定保留優先權。預設系統管理員仍依原有 M365 登入規則授權。
- M365 明確停用的員工會停用本機帳號，既有 Session 後續請求亦失效。M365 啟用不會覆寫本機管理員的停用狀態；復職需由管理員核對後重新啟用。
- 員工部門清空時，移除其舊部門歸屬，避免繼續使用舊部門權限；其個人設定及歷史案件保留，登入仍要求 M365 部門資料完整。
- 清單暫時缺少的員工、舊部門及本機歷史帳號不直接刪除或合併，避免破壞歷史外鍵；因此選單仍可能含歷史項目。同步期間部門主檔改為管理後台唯讀，部門來源由 M365 維護。
- Graph 部門來自使用者屬性；完全沒有任何成員填入的部門，無法從此來源取得。同步包含成員類型的停用帳號與服務帳號；不含 Guest。

本次實際連線回傳授權不足；完成上列 Application 權限及管理員同意後，已啟動的 worker 會自動重試。尚未宣稱已取得公司完整清單。
