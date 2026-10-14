# 備份、獨立還原與驗證

從[README](../README.md)開始。此流程不重設demo，不覆寫`.env`，不降版已發布migration。備份含帳號及業務資料，只存本機忽略的`instance/backups/`，勿提交或貼到聊天。

1. 停止Flask及其他寫入程序，禁止備份期間做DDL或業務寫入。`--single-transaction`保護InnoDB一致性；表筆數前後核對可拒絕明顯變動，但不能取代停止寫入。
2. 確認MySQL客戶端與來源服務版本相容。在專案根目錄執行；各組員調整自己的客戶端路徑：

```powershell
.\.venv\Scripts\python.exe scripts/backup_database.py backup --source demo --file instance/backups/before-upgrade.sql --mysql-bin 'C:\Program Files\MySQL\MySQL Server 9.6\bin'
```

預期`BACKUP PASS`，保存SQL及`.manifest.json`（SHA256、各表筆數、migration）。已有檔案拒絕覆蓋，下一次換新檔名。腳本以子程序環境傳密碼，命令列及回報不輸出憑證。

3. 由DB管理者另外建立空白`system2_姓名_restore_test`與只限該庫的還原帳號，不能用目前demo／test DB。可在同一MySQL或另一獨立本機實例還原；沒有建庫權限由DB管理者建立，不能reset原庫。
4. 在目前PowerShell暫設`RESTORE_DATABASE_URL`，填新建還原庫的mysql+pymysql連線；不將憑證加入檔案或Git。執行：

```powershell
.\.venv\Scripts\python.exe scripts/backup_database.py restore --file instance/backups/before-upgrade.sql --confirm-empty-restore --mysql-bin 'C:\Program Files\MySQL\MySQL Server 9.6\bin'
.\.venv\Scripts\python.exe scripts/backup_database.py verify --file instance/backups/before-upgrade.sql
```

預期兩次`RESTORE VERIFY PASS`。來源校驗碼錯誤、目標非空、名字沒有restore、與來源或日常test同名均拒絕，不刪目標資料。還原失敗保留現場，換另一空庫重試；SQL與manifest須成對保存。

5. 用還原庫啟動獨立核對應用：暫設`APP_ENV=test`、`TEST_DATABASE_URL=$env:RESTORE_DATABASE_URL`、清除MODULE_DEV，先db upgrade／db check，再於5010啟動Flask。這是還原核對，不要跑會清理已提交test資料的併發fixture或reset-demo。
6. 核對原身份登入、本店／他店隔離；抽樣單號、不可變原訂量、承諾與物流ETA、庫存可售／損壞量、異動來源、收貨／差異及確認快照。對照備份前記錄，記下SHA、MySQL版本、備份日期、筆數及抽樣結果。
7. 完成後清除上述暫設環境，返回原`.env`。資料回復至日常環境前由A核對目標、停止寫入並備份現況；腳本只還原獨立空庫，不自動切換或覆蓋日常DB。

本次AI實際從原demo建立備份，在獨立MySQL9.6／3309還原，再從884e7a53a8c8升級a1410260003，db check無差異；另建空庫從零升級、db check／heads通過。完整業務內容核對見[修正報告](system-hardening-2026-10-14.md)。備份與還原資料保留本機，不納版控。
