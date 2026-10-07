# 統家便利店補貨系統

產品規則以 spec.md 為準，分工與發布程序以 agent.md 為準。此版本為 A 的共用基礎，尚未完成訂購、庫存與履約業務。

## 本機環境（PowerShell，Python 3.12／MySQL 8.4 以上）

每人使用獨立 checkout 與資料庫；例如 A 使用 system2_a_demo、system2_a_test，B 改為 system2_b_demo、system2_b_test。資料表採 InnoDB、utf8mb4。先由本機 DB 管理者建立空資料庫及僅限該 DB 的帳號，不共用錄影資料。

```powershell
git clone https://github.com/KL-0728/system2.git
cd system2
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 .env 填入兩個本機連線、自己產生的 SECRET_KEY 與至少12字元的 DEMO_PASSWORD。不將密碼貼到 PR／聊天，不提交 .env。

```powershell
.\.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m flask --app wsgi seed-demo
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

開啟 http://127.0.0.1:5000/login，使用 manager1（DEMO1）、manager2（DEMO2）、operator（統家接單）或 admin（管理者）；密碼均取自本機 DEMO_PASSWORD，僅為合成示範帳號。示範起點為 2026-10-08 21:00 Asia/Taipei，時間暫停；所有頁面持續標示示範時間。完整管理介面留 A04。

## 測試與防誤用

```powershell
$env:APP_ENV='test'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m flask --app wsgi db check
Remove-Item Env:APP_ENV
```

測試只讀 TEST_DATABASE_URL；缺少設定立即失敗，不回退 demo 或 SQLite。demo／test 僅允許 localhost／127.0.0.1，DB 名稱須為 system2_*_demo／system2_*_test，測試與 demo 不得為同一 DB。測試在獨立外層交易內建立種子，結束回滾，不執行 drop_all；test DB 必須先套 migration，且不得預先放入其他人的資料。

## A02 實測

1. 按環境段落遷移及建立種子，GET /health → status 為 ok；登入頁標示示範時間。
2. manager1 登入 → 首頁顯示帳號。以 GET /api/auth/me 取得該店 id；GET /api/stores/{本店id}/context → 200。
3. manager1 存取另一店 context → 404；未登入存取 → 401；無 CSRF 的 POST 登入／登出 → 400。不要把前端隱藏按鈕視為權限證據。
4. 執行 tests/test_permissions.py 與 tests/test_foundation.py → 覆蓋錯密碼、停用帳號、角色拒絕、時鐘倒退與正式模式拒絕、版本衝突及 Decimal/null。
5. 正式模式禁止模組替身、debug、不安全 cookie 及停用 CSRF。尚未完成公開上線部署；登入速率限制目前採單程序記憶體，正式多程序需另設共享儲存。

瀏覽器可先 GET /api/auth/csrf 取得 token，POST JSON 時以 X-CSRFToken header 傳入；登入成功會回新 token。一般 HTML 表單已帶 CSRF。所有後端操作仍須用服務端身份檢查角色與門市。

## 安全示範重設

```powershell
.\.venv\Scripts\python -m flask --app wsgi reset-demo
```

只可於本機 APP_ENV=demo 使用，輸入有效 admin 帳密及 `RESET LOCAL DEMO`。刪除此 demo DB 資料並重建案例；不更動 schema／migration。不可對錄影、他人或正式 DB 執行；測試環境拒絕此命令。重設後才可回到案例起點。

## Git 協作

本次 A01–A03 經 A 明確授權直接推 main、不開 PR。B／C／D 仍依 agent.md：A03 發布後從 main 各開 feat/b-module、feat/c-module、feat/d-module，沿01→05連續製作；人工實測後交 PR，僅 A 合併。未發布前不可宣稱可開工。

發布狀態見 docs/parallel-ready.md（A03 建立後），介面見 docs/contracts.md，任務見 docs/tasks.md，驗收見 docs/acceptance.md。
