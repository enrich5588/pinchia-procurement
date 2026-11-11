# M365 登入與 Graph 部門同步

本專案已改用 Microsoft Entra ID 單一租用戶登入。採用 MSAL Python 的 authorization code flow 與 PKCE，應用程式另外驗證 ID token 簽章、issuer、audience、期限及 nonce，再呼叫 Microsoft Graph `/me` 讀取部門。

## 公司端需提供的設定

在公司租用戶建立 **Web／Single tenant** 應用程式。申請 Microsoft Graph **Delegated `User.Read`**；OIDC 的 `openid`、`profile` 由 MSAL 加入。本版本只在登入時同步資料，排除 `offline_access`，不保存 access token、ID token 或 refresh token。

| 環境變數 | 用途 |
| --- | --- |
| `M365_TENANT_ID` | 公司 Directory／Tenant ID，GUID |
| `M365_CLIENT_ID` | App registration 的 Application／Client ID，GUID |
| `M365_REDIRECT_URI` | Entra 登記的完整回呼網址 |
| `M365_CERT_PRIVATE_KEY_PATH` | Server 上的 RSA PEM 私鑰絕對路徑，勿提交版控 |
| `M365_CERT_THUMBPRINT` | 已登記憑證的 SHA-1 thumbprint，與私鑰配對 |
| `M365_CLIENT_SECRET` | 選用：Client secret 的 Value，非 Secret ID；與憑證二擇一 |
| `M365_ALLOW_GUESTS` | 預設 false，拒絕 Guest／非 Member 帳號 |
| `ALLOW_LOCAL_LOGIN` | 預設 false；只有明確設 true 才允許維護／開發用本機密碼登入 |

正式環境建議使用憑證；請由資訊部將私鑰配置於 Server 的受限位置。開發環境也可使用 Client secret。不要將密鑰、私鑰或使用者 token 放進聊天、前端、Git 或日誌。

回呼路徑固定為 `/accounts/microsoft/callback/`：

```text
開發：http://localhost:8000/accounts/microsoft/callback/
正式：https://procurement.公司網域/accounts/microsoft/callback/
```

這些網址必須由 Entra 管理員登記。開發的 HTTP 只接受 DEBUG 模式下的 localhost。正式設定須 HTTPS；`DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS` 亦需配合網域。登入若從不同主機名稱開始（例如 127.0.0.1 與 localhost 混用），會先導回已設定的主機，再開始登入，避免回呼找不到 Session cookie。

缺少設定時，登入頁顯示明確提示並停用 M365 按鈕；不會自動降級開放密碼登入。可離線檢查設定格式：

```powershell
./.venv-rebuild/Scripts/python.exe manage.py check_m365
```

此命令不連線 Microsoft、不驗證公司端核准狀態，也不輸出密鑰。仍需實際登入確認憑證、Graph 權限、條件式存取與部門資料。

## 登入與部門規則

1. 在站內以受 CSRF 保護的 POST 開始登入，建立伺服器端 Session，保留 state、nonce 與 PKCE flow；要求 10 分鐘內完成，同一 Session 新登入會替換舊流程。
2. Microsoft 登入完成後回到 callback。回呼消耗一次性 flow，再以後端憑證交換 token。
3. 使用固定公司租用戶的 Microsoft JWKS 驗證 RS256 簽章；檢查 issuer、Client ID、有效時間、必要 claims 與送出的 nonce。不使用瀏覽器傳入的使用者資料作為信任來源。
4. 確認 token 的 Tenant ID 後，帶 access token 呼叫：

```http
GET https://graph.microsoft.com/v1.0/me?$select=id,displayName,userPrincipalName,mail,department,userType
```

5. Graph `id` 必須與驗證後的 `oid` 一致。`department` 去除頭尾空白後，同步至 `Department`／`UserProfile`；部門未設定、身分不符、停用帳號或不允許的來賓均拒絕登入，不沿用過期本機部門來完成登入。
6. 新建帳號有不可使用的本機密碼，且不自動取得 Django staff／superuser。新帳號的 username 優先使用 UPN；若重複或過長則採不衝突的識別名稱。後續以穩定的 Tenant ID＋Object ID 找回同一帳號，UPN 或信箱變更不會改綁帳號。
7. 成功登入的本機 Session 有效 8 小時；部門於每次 M365 登入同步。此版本沒有背景全員目錄同步，也不會讓尚未登入的人員自動出現在保管人選單。

部門正式名稱為 `管理與事業發展部`，由 Graph `user.department` 同步。業務權限依「個人設定 → 部門設定 → 系統預設」判斷，設定方式見 [權限管理說明](PERMISSIONS.md)。預設管理員 `tonychi@pin-chia.com`（`M365_DEFAULT_ADMIN_UPN`）經公司租用戶與 Graph 成員身分驗證後，自動取得系統管理員權限；其他帳號維持一般權限，既有主管或指定簽核人設定不變。

站內登出會清除本系統 Session 並回登入頁；不登出其他 Microsoft 365 應用程式。再次點 M365 登入可能使用既有 Microsoft SSO，並顯示帳號選擇。

## 既有帳號與案件保留

**不以信箱、UPN 或信箱前綴自動綁定既有帳號。** 若要讓 M365 帳號延續既有申請、簽核紀錄與角色，應在該人首次 M365 登入前，由管理員確認其 Object ID 並執行：

```powershell
./.venv-rebuild/Scripts/python.exe manage.py link_m365_identity --username wang --tenant-id <公司Tenant-ID> --object-id <該員工Object-ID>
```

指令會保留原 User 主鍵、username、密碼及 staff／superuser 權限，只新增身分綁定。相同綁定可重跑；遇到身分已被其他帳號綁定或帳號已綁其他身分時會停止，不會覆寫或轉移。

既有簽核路徑仍使用 wang／kao／gardine／hu，因此需將四位實際簽核人的 Entra Object ID 分別綁到既有帳號；不要單憑相同姓名猜測。若已有 M365 新帳號及案件，不應直接改綁，需另做有明確對照與備份的資料整併。

在關閉本機登入前，也應完成至少一位管理員的 M365 綁定。缺少公司設定時，可經明確設定 `ALLOW_LOCAL_LOGIN=true` 暫用本機維護登入；完成設定後改回 false。本系統未因這次改版自動建立或綁定公司管理員。

M365 綁定亦可由已登入的系統管理員在 Django 管理後台維護；對既有高權限帳號的綁定需核對人員與 Object ID。

## 內部 Server 部署

- 公司內部 DNS 將正式子網域指向內部 Server／反向代理，員工瀏覽器須能透過內網或 VPN 存取該網址。
- Server 須能對外以 HTTPS 連線至 Microsoft 登入／token／JWKS 服務及 `graph.microsoft.com`；員工瀏覽器也須能連到 Microsoft 登入相關服務。
- 使用正式 WSGI／ASGI server 與 HTTPS 反向代理，勿以開發 runserver 作正式服務。
- 若代理終止 HTTPS 並以 HTTP 轉送 Django，只有在代理會移除／覆寫用戶提供的 `X-Forwarded-Proto` 且後端僅接受可信代理時，才設定 `DJANGO_TRUST_PROXY_HTTPS=true`。否則保留 false。
- Session 必須存於伺服器端；不支援 signed-cookie Session backend 儲存 OAuth flow。
- callback 使用 query response mode，access token 不經 query string 傳送；正式 access log 應遮蔽 callback 查詢字串中的一次性 code／state。
- 憑證／secret 到期與輪替由資訊部管理；部門來源及帳號停用政策應納入上線驗收。

## Migration 與測試

新增 `organization/migrations/0002_microsoft_identity.py`，保留既有 `platform_stub` app label，僅增加身分綁定資料表及唯一約束；不重建既有業務資料表。

```powershell
./.venv-rebuild/Scripts/python.exe -m pip install -r requirements.lock
./.venv-rebuild/Scripts/python.exe manage.py migrate
./.venv-rebuild/Scripts/python.exe manage.py test organization.test_microsoft
./.venv-rebuild/Scripts/python.exe manage.py test
```

M365 專項測試包括合法／偽造的 RSA 簽署 token、issuer／audience／期限／nonce 錯誤、state／逾時／重播、跨租用戶、Graph 身分不符／連線失敗、空部門／來賓、停用帳號、既有身分綁定唯一性、信箱相同不得接管、本機與管理站密碼登入封鎖等。

本次完整測試 214 項全部通過，其中 M365 專項 35 項；系統、migration 差異與依賴檢查通過。已備份並套用身分綁定 migration，瀏覽器確認登入頁顯示 M365 登入與尚未設定提示。

缺少公司 Tenant ID、Client ID、有效憑證／secret 及已登記的回呼網址時，只能完成本機自動測試與未設定頁面檢查，無法完成真實租用戶的登入驗收。填妥 `.env` 後必須重新啟動服務；只重新整理瀏覽器不會重新讀取環境設定。

## 官方參考

- [MSAL Python](https://msal-python.readthedocs.io/en/latest/)
- [授權碼流程](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [Graph 讀取使用者](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0)
- [User department 欄位](https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0#properties)
- [Entra token claims 與穩定身分識別](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)
