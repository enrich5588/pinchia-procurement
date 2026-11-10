# 整合契約 — 你的 app 如何進主平台

## 1. 邊界

你開發的範圍 = `procurement/` 這個 Django app。
`platform_stub/`、`stubsite/` 是平台替身,**唯讀** —— 你不改它們;
覺得替身缺了什麼,開 issue 告訴 AI 資訊部,不要自己補。

## 2. 穩定介面(只能依賴這些)

| 你 import 的 | 整合時換成 | 說明 |
|---|---|---|
| `platform_stub.models.Department` | 主平台同名模型 | 只保證 `name` 欄位 |
| `platform_stub.models.UserProfile` | 主平台同名模型 | 只保證 `user`/`department` |
| `platform_stub.models.user_department()` | 平台工具 | 取部門;superuser 可能回 None |
| `platform_stub.gate.feature_required` | 平台 feature_gate | 功能上線閘門 |
| Django auth(`request.user`,`@login_required`) | 公司 MS365 SSO | 你不碰登入實作 |

沒列在表裡的,一律視為不存在。

## 3. 程式慣例(審查會逐條看)

1. 改資料一律 POST;GET 無副作用。
2. 權限檢查在 server 端 view 裡做;前端的隱藏/disabled 只是提示,不是防線。
3. **禁用瀏覽器原生 `confirm()`/`alert()`/`prompt()`**;要確認就做兩段式站內 UI。
4. 錯誤要吵:擋下操作時用 messages 給人看得懂的原因;絕不 `except Exception: pass`。
5. 每個行為配測試;邊界情況(併發重號、倒退狀態、替別人簽收)必須有反例測試。
6. 樣板一律 `{% extends "base.html" %}`,不寫死顏色字型(整合時換主站樣式)。

## 4. AI 工具使用規範(手冊第十四章第十四條)

用 AI 輔助開發 OK,但**只准把本 repo 的內容**貼給 AI —— 本 repo 不含公司資料,
這是它存在的理由之一。任何公司文件、真實同仁資料、主平台程式碼,
一律不得輸入未經公司核准的 AI 平台(清單:向 AI 資訊部索取)。

## 5. 交付與審查

1. 交付 = `manage.py test procurement` 全綠 + push 到本 repo 的 feature branch + 開 PR。
2. AI 資訊部先做整合預檢,然後進平台標準流程:**兩位獨立審查者**(自動化)逐行審,
   FAIL 會附行號與反例,照單修完重送;雙 PASS 才 merge 進主平台。
3. 上線節奏由平台管:先 Develop 級(僅管理員可見)→ dev 站實測 → 資訊長放行。

## 分工邊界(2026-08-21 更新)

- 本 repo=齊軒(procurement/signoff)。常逸的報修申請已拆到獨立 repo
  pinjia-repairs(Leo 裁定分開)。
- 在 feature branch 工作(feat/<主題>),完成開 PR 由小西審;不直接 push main。
- 測試鐵律:每個「不可以」都要有反例測試。

