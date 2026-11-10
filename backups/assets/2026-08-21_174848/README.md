# 財產清冊備份

- 建立時間：2026-08-21 17:48:48（Asia/Taipei）
- 資產筆數：15
- 財產編號：PINA00001～PINA00015
- 建立日期缺漏：0
- 修改日期缺漏：0
- 建立者缺漏：0
- 最後修改者缺漏：0

## 備份檔

- `db_snapshot.sqlite3`：完整 SQLite 資料庫快照，包含帳號、部門、資產與稽核資料。
- `assets_fixture.json`：UTF-8 Django fixture，只包含 `assets.Asset` 的 15 筆資料。

## SHA-256

```text
E81685088A499954AE70D78568D4E39C7FC5CBBBDC3BEAF7DCFFA91D3EE77047  assets_fixture.json
E9A9DBB544562CD118286BC997B8FB0A37C4347D19086BFFDC018621DA5D711F  db_snapshot.sqlite3
```

## 還原方式

還原會覆蓋或新增目前資料，執行前應先停止開發伺服器並再次備份現況。

完整還原：以 `db_snapshot.sqlite3` 取代專案根目錄的 `db.sqlite3`。

只還原資產：確認資料庫中的資產資料已妥善處理後執行：

```powershell
.\.venv\Scripts\python.exe manage.py loaddata backups\assets\2026-08-21_174848\assets_fixture.json
```

Fixture 內的部門與使用者使用既有資料庫主鍵；若還原到不同環境，應先確認對應的部門及帳號存在。
