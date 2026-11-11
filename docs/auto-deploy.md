# Linux VM 自動部署（main → GitHub Actions → Docker）

這套設定適用於單台 Ubuntu/Linux x64 VM：GitHub 託管 runner 先測試，通過後由 VM 上的 self-hosted runner 部署同一個 commit。VM 主動透過 HTTPS 連線 GitHub，不需要為部署開放公網 SSH。Django 使用 Gunicorn，Caddy 提供 HTTPS 與公開靜態檔；私有附件仍由 Django 驗證權限後提供。

每次部署會先建置映像及檢查設定，再停止 web、備份資料庫與附件、執行 migration、收集靜態檔案、啟動服務並等候健康檢查。更新期間有短暫停機，不支援多 VM 共用 SQLite。資料在 `/srv/pinjia/shared/data`，不放在 runner 的工作目錄。

## 1. 準備 VM 與網域

- 安裝 Git、Python 3、tar、util-linux（提供 flock），以及 [Docker Engine 與 Compose plugin](https://docs.docker.com/engine/install/ubuntu/)。Compose 需 **2.30.0 以上**，用於原樣載入 secret，避免 `$` 被展開。
- VM 需能對外連線 GitHub、Docker/Python 套件來源，以及 Microsoft 登入和 Graph 服務。
- 將正式網域 DNS 指向 VM／入口 NAT。此預設使用 Caddy 自動申請公信憑證，外部必須能透過 TCP 80、443 到達 Caddy，且不可已有其他服務占用這兩個埠。
- 若是**純內網網域或既有 HTTPS 反向代理**，先調整 `deploy/Caddyfile` 的憑證／代理方案；預設公信憑證設定不適用。公司現有反向代理的憑證、port、轉送規則須先確認。

### 評估階段：VM 8000 與對外埠

目前 VM 尚未建立，固定 IP 的對外埠也尚未決定；以下是可選拓樸，不代表已上線。

建議對外維持標準 HTTPS 443，入口設備將它轉送到 VM 的 8000：

```text
使用者 https://採購網域
  → 固定 IP:443（NAT，保留 TLS）
  → VM:8000（HTTPS）
  → Caddy 容器:443（終止 TLS）
  → Django 容器:8000（內部 HTTP）
```

此時在 `shared/server.env` 設 `HTTPS_PORT=8000`。VM 8000 是 Caddy 的 HTTPS 入口；Django 容器內的 8000 不直接發布到主機。對外 80 也需轉送到 `HTTP_PORT` 指定的 VM 埠，以支援預設 HTTP 轉址與憑證驗證。M365 回呼與 CSRF origin 仍使用不帶埠的 `https://採購網域`。

若對外只能使用例如 8443，使用者網址、M365 callback 與 CSRF origin 都需加入 `:8443`，並額外調整 Caddy 的站台網址／轉址與憑證驗證方式；**只修改 `HTTPS_PORT` 不足以完成此拓樸**。若固定 IP 的 443 已有公司入口代理，可讓該代理依子網域分流，再依其 TLS 終止方式調整本專案設定。DNS 只指向 IP，無法指定服務埠。

## 2. 建立部署帳號與持久化目錄

在 VM 以有 sudo 權限的管理員執行：

```bash
sudo adduser --disabled-password --gecos '' pinjia-deploy
sudo usermod -aG docker pinjia-deploy
# 容器內 app 的 UID/GID 固定為 10001；確認未被其他帳號占用。
getent passwd 10001 || true
getent group 10001 || true
# 若 10001 已屬其他用途，先調整 Dockerfile 的 UID/GID 與以下指令。
sudo groupadd --gid 10001 pinjia-data
sudo usermod -aG pinjia-data pinjia-deploy
sudo install -d -o pinjia-deploy -g pinjia-deploy -m 700 /srv/pinjia
sudo install -d -o pinjia-deploy -g pinjia-deploy -m 700 \
  /srv/pinjia/shared /srv/pinjia/releases /srv/pinjia/backups
sudo install -d -o 10001 -g 10001 -m 2770 \
  /srv/pinjia/shared/data /srv/pinjia/shared/data/private-media
sudo install -d -o pinjia-deploy -g pinjia-deploy -m 755 /srv/pinjia/shared/secrets
```

重新登入部署帳號使群組生效；確認 `docker info` 和 `docker compose version` 正常。Docker 群組能控制 VM，這台 runner 應專供可信任的部署工作。不要在此 runner 執行外部 PR；本專案的 PR 測試使用 GitHub 託管 runner。公開儲存庫尤其應評估 [GitHub 的 self-hosted runner 安全限制](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners)，可另用私有部署儲存庫隔離 runner。

## 3. 正式環境設定與既有資料

以 `pinjia-deploy` 帳號從專案複製：

```bash
cp deploy/production.env.example /srv/pinjia/shared/production.env
cp deploy/server.env.example /srv/pinjia/shared/server.env
chmod 600 /srv/pinjia/shared/*.env
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
nano /srv/pinjia/shared/production.env
nano /srv/pinjia/shared/server.env
```

填入真實網域、剛產生的 `DJANGO_SECRET_KEY` 及 M365 設定。兩份範例中的 `procurement.example.com` 都要替換。env 使用字面值，不加外層引號、不使用 shell 變數。secret 只留在 VM，不放入 GitHub 或 Git。

M365 回呼必須是 `https://你的網域/accounts/microsoft/callback/`，也需在 Entra 登記。若使用憑證，把私鑰放入 `shared/secrets`，在 env 設定容器路徑，例如 `/run/secrets/m365.pem`；檔案要讓 UID/GID 10001 可讀、其他使用者不可讀。詳見 [M365 設定](m365-login.md)。

有既有資料時，**先停止舊系統所有寫入**，再把 `db.sqlite3` 和 `private-media/` 複製到 `shared/data/`。不要覆蓋正在使用的資料庫，也不要只複製仍在寫入的 SQLite 主檔而漏掉 WAL。可使用 SQLite backup API 產生完整快照。複製後由管理員設定：

```bash
sudo chown -R 10001:10001 /srv/pinjia/shared/data
sudo chmod -R u=rwX,g=rX,o= /srv/pinjia/shared/data
```

新部署會自動建立空資料庫並 migration；不會建立 demo 資料或同步本機未提交的資料。

## 4. 安裝 GitHub runner 與啟用自動部署

1. 在此 GitHub 儲存庫的 **Settings → Actions → Runners → New self-hosted runner** 選 Linux x64。
2. 以 `pinjia-deploy` 登入，在其 home 下建立 runner 目錄，依 GitHub 當下提供的下載／註冊命令安裝。不要以 root 執行 runner。註冊時加入自訂 label：**`pinjia-production`**。
3. 在 runner 目錄執行 `sudo ./svc.sh install pinjia-deploy`、`sudo ./svc.sh start`，讓 VM 重啟後自動執行。若後來變更群組，重啟 runner service。
4. 在 **Settings → Environments** 建立 `production`，將可部署分支限制為 `main`。若希望完全自動部署，不設定 required reviewers；可用性依 GitHub 方案而定。
5. 將本次部署檔案連同需要上線的應用程式修改，經審查後合併到 `main`。本機未提交或其他分支的內容不會部署。
6. 在 **Actions → Test and deploy** 查看測試與部署結果。之後每次 push／merge 到 `main` 都會觸發。也可選 `main` 執行 **Run workflow**。

本地與 Actions 都有部署鎖，避免同時修改資料庫。測試、建置或正式設定檢查失敗時不停止現有服務。資料備份之後若 migration／啟動失敗，腳本會停止 web 並回報失敗，留待檢查；不會自動把已變更的資料庫交給舊版本程式。

## 5. 檢查與復原

成功後 `/srv/pinjia/current` 指向目前 release，目錄名稱就是已部署的 commit。以部署帳號查看：

```bash
export DEPLOY_ROOT=/srv/pinjia
export RELEASE="$(basename "$(readlink /srv/pinjia/current)")"
cd /srv/pinjia/current
docker compose --env-file /srv/pinjia/shared/server.env -f deploy/compose.yaml ps
docker compose --env-file /srv/pinjia/shared/server.env -f deploy/compose.yaml logs --tail 100 web proxy
```

確認正式 HTTPS、登入頁、M365 真實登入、附件權限及靜態檔案。健康檢查只確認登入頁與資料庫連線，不代替 M365 端到端驗收。Caddy 與 Gunicorn 的 access log 預設關閉，避免記錄 OAuth callback 的 code／state。

每次部署的備份在 `/srv/pinjia/backups/<時間>-<新commit>.tar.gz`，包含停止寫入時的整個 `data/`；旁邊的 `.previous-release` 記錄對應舊程式路徑。**第一次部署前另存一份原始資料備份**。本流程不自動刪備份、release 或映像；需監控磁碟、定期保留與將備份複製到 VM 以外的受限位置。

復原時先停止 web，檢查失敗階段與 migration 紀錄：

- 尚未 migration 且資料確認未變更時，可針對先前 release 設定 `RELEASE`、重新 collectstatic，再 `up -d --wait`。
- migration 已執行或無法確認時，先另外備份失敗後現況，再由管理員將選定 tar 備份解壓到**新的空目錄**並核對內容；停止 web 後切換 `shared/data` 至還原資料、修正 UID/GID 10001，使用 `.previous-release` 指定的舊版映像重新收集靜態檔並啟動。舊版啟動通過後再更新 `current` symlink。
- 還原備份會捨棄備份後新增資料；不要直接重跑舊 workflow 來假設資料庫可以降版，也不要使用 `docker compose down -v` 刪掉持久化 volume。

VM／GitHub runner 失聯時新版本不會部署；現有容器會繼續服務，重開機後由 Docker 的 restart policy 啟動。部署中斷或被人工取消時，先檢查實際容器與資料庫狀態，再決定續跑或復原。

參考：[Compose 正式環境部署](https://docs.docker.com/compose/how-tos/production/)、[GitHub runner 安裝](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)、[Caddy HTTPS](https://caddyserver.com/docs/automatic-https)。
