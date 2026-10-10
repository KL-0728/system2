# 統家便利店補貨系統

產品規則以 spec.md 為準，分工與發布程序以 agent.md 為準。此版本已接入C訂購模組；B庫存／計算與D履約尚待真實整合。

**A本次補修的預覽與測試請看[逐步操作指南](docs/a-manual-testing.md)**。網站需Flask＋MySQL，不能只用Live Server打開HTML。

**組員先看[操作入口：現在要做什麼](docs/team-start.md)**：包含首次安裝、每日啟動、示範帳密、跨店檢查圖例、錯誤判讀，以及各狀態可直接貼給Codex的下一句。下文保留環境與技術細節。

## 本機環境（PowerShell，Python 3.12／MySQL 8.4 以上）

每人使用獨立 checkout 與資料庫；例如 A 使用 system2_a_demo、system2_a_test，B 改為 system2_b_demo、system2_b_test。資料表採 InnoDB、utf8mb4。先由本機 DB 管理者建立空資料庫及僅限該 DB 的帳號，不共用錄影資料。

```powershell
git clone https://github.com/KL-0728/system2.git
cd system2
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 .env 填入兩個本機連線、自己產生的 SECRET_KEY 與至少8字元的 DEMO_PASSWORD。DEMO_PASSWORD可供本機合成示範帳號共用，勿使用真實帳號的密碼；不將本機憑證貼到PR／聊天，不提交.env。修改此設定不會自動更新既有帳號，僅影響後續建立或重設示範資料。

```powershell
.\.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
$env:APP_ENV='test'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
$env:APP_ENV='demo'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m flask --app wsgi seed-demo
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

開啟 http://127.0.0.1:5000/login，使用 manager1（DEMO1）、manager2（DEMO2）、operator（統家接單）或 admin（管理者）；密碼均取自本機 DEMO_PASSWORD，僅為合成示範帳號。示範起點為 2026-10-08 21:00 Asia/Taipei，時間暫停；所有頁面持續標示示範時間。完整管理介面留 A04。

新版.env.example的合成示範密碼為managerps。既有資料庫沿用建立帳號時的密碼，單改.env不會同步更新；保留資料改密碼的方法見操作入口。SECRET_KEY的產生指令僅顯示新值，須先自行填入.env再啟動Flask。

## 每次重新開工（所有成員）

首次安裝完成後，不必再次clone、複製.env或seed-demo。先啟動自己.env連到的MySQL服務，再執行下列唯讀檢查；確認demo與test皆PASS後才啟動應用或執行測試。

```powershell
.\.venv\Scripts\python scripts/check_environment.py
```

若提示migration落後，在對應APP_ENV下執行db upgrade後重查。測試後啟動瀏覽器實測時，明確設APP_ENV=demo，避免同一個PowerShell殘留APP_ENV=test。MODULE_DEV依自己的B／C／D模組設定。A專用3307啟動腳本僅適用A既有資料目錄，其他組員啟動自己的MySQL。

## 測試與防誤用

先確認資料庫正在執行。A 的這份既有 checkout 使用獨立 MySQL **3307**，它不是 Windows 的 MySQL96／3306 服務，重開電腦後須重新啟動；不能只啟動 Flask。保留既有 .env 與資料，**不要重新複製 .env.example、初始化或重設資料庫**。

```powershell
# 僅 A 此份既有 checkout；B／C／D 啟動自己的 MySQL 服務。
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_a_mysql.ps1
.\.venv\Scripts\python scripts/check_environment.py
```

預期：demo、test 各一行 PASS，且 migration head 為884e7a53a8c8。此檢查只讀，不清資料、不輸出密碼。若 FAIL，先解決提示的連線／認證／migration問題，再跑測試。啟動腳本只啟動既有 A 資料目錄；已啟動會直接返回，不重複建立程序。

```powershell
$env:APP_ENV='test'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m flask --app wsgi db check
Remove-Item Env:APP_ENV
```

若結果是 `10 passed, 26 errors` 且錯誤含 MySQL `2003`／Connection refused，代表無DB的測試通過，但需要DB的測試無法連線。請先執行上面的檢查；不要用重設資料或改成SQLite處理。`check_environment.py --database test` 可只檢查測試DB。

測試只讀 TEST_DATABASE_URL；缺少設定立即失敗，不回退 demo 或 SQLite。demo／test 僅允許 localhost／127.0.0.1，DB 名稱須為 system2_*_demo／system2_*_test，測試與 demo 不得為同一 DB。測試在獨立外層交易內建立種子，結束回滾，不執行 drop_all；test DB 必須先套 migration，且不得預先放入其他人的資料。

## A02 實測

1. 按環境段落遷移及建立種子，GET /health → status 為 ok；登入頁標示示範時間。
2. manager1 登入 → 首頁顯示帳號。以 GET /api/auth/me 取得該店 id；GET /api/stores/{本店id}/context → 200。
3. manager1 存取另一店 context → 404；未登入存取 → 401；無 CSRF 的 POST 登入／登出 → 400。不要把前端隱藏按鈕視為權限證據。
4. 執行 tests/test_permissions.py 與 tests/test_foundation.py → 覆蓋錯密碼、停用帳號、角色拒絕、時鐘倒退與正式模式拒絕、版本衝突及 Decimal/null。
5. 正式模式禁止模組替身、debug、不安全 cookie 及停用 CSRF。尚未完成公開上線部署；登入速率限制目前採單程序記憶體，正式多程序需另設共享儲存。

瀏覽器可先 GET /api/auth/csrf 取得 token，POST JSON 時以 X-CSRFToken header 傳入；登入成功會回新 token。一般 HTML 表單已帶 CSRF。所有後端操作仍須用服務端身份檢查角色與門市。

## A03 自動測試通過後的人工核對

使用既有示範資料，不需重設。先完成環境檢查，再於PowerShell啟動C模組基礎頁：

```powershell
$env:APP_ENV='demo'
$env:MODULE_DEV='C'
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

1. 一般瀏覽器開啟 http://127.0.0.1:5000/login，以manager1及本機.env的DEMO_PASSWORD登入。預期首頁顯示帳號與示範時間。
2. 開啟 http://127.0.0.1:5000/modules/c/，預期有測試／未真實整合標示；這是基礎頁，不代表C訂購功能完成。開啟/modules/b/應為404，因本次只啟用C。
3. 依[跨店權限逐步指引](docs/team-start.md#5-跨店權限先查身份再看資料)分別在一般／無痕視窗登入manager1／manager2，先查username，再記下stores內的門市id；最外層id是帳號id。
4. 依該指引驗證兩位店長：本店200、他店404。回報時附帳號、門市id及實際結果；讀到DEMO2資料須先確認當時是否為manager2，不能單憑JSON判定隔離通過。
5. 完成後回PowerShell按Ctrl+C停止Flask，清除本次設定：

```powershell
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
Remove-Item Env:APP_ENV -ErrorAction SilentlyContinue
```

記錄實測版本、步驟與結果。A03只驗證共用基礎及模組隔離；真實訂購、庫存與收貨流程待模組開發及A05／A06整合驗收。

## 安全示範重設

```powershell
.\.venv\Scripts\python -m flask --app wsgi reset-demo
```

只可於本機 APP_ENV=demo 使用，輸入有效 admin 帳密及 `RESET LOCAL DEMO`。刪除此 demo DB 資料並重建案例；不更動 schema／migration。不可對錄影、他人或正式 DB 執行；測試環境拒絕此命令。重設後才可回到案例起點。

## Git 協作

本次 A01–A03 經 A 明確授權直接推 main、不開 PR。B／C／D 仍依 agent.md：A03 發布後從 main 各開 feat/b-module、feat/c-module、feat/d-module，沿01→05連續製作；人工實測後交 PR，僅 A 合併。未發布前不可宣稱可開工。

發布狀態見 docs/parallel-ready.md（A03 建立後），介面見 docs/contracts.md，任務見 docs/tasks.md，驗收見 docs/acceptance.md。

## A03：B／C／D 各自開工

首次 clone 後先讀 docs/parallel-ready.md，核對最新發布標記a03-parallel-v2與合約v1。若工作目錄乾淨，依序執行（B 範例，C／D 換自己的分支）：

```powershell
git status --short --branch
git remote -v
git fetch origin
git switch main
git pull --ff-only origin main
git fetch origin --tags
git merge-base --is-ancestor a03-parallel-v2 HEAD
git switch -c feat/b-module
```

各人按前述環境段落建立自己的 demo／test DB、.env、安裝、migration、seed-demo；只第一次 seed-demo，已有資料會拒絕覆蓋。示範資料為兩店、10品項、各14日歷史銷售；現貨20、不可售0，已核對盤點基準為2026-10-08 21:00。歷史資料不再次扣庫存。

| 成員 | 分支 | MODULE_DEV | 登入身份 | 基礎檢查 URL | 外部供應者替身 |
| --- | --- | --- | --- | --- | --- |
| B | feat/b-module | B | manager1 | http://127.0.0.1:5000/modules/b/ | D 未結來源 |
| C | feat/c-module | C | manager1 | http://127.0.0.1:5000/modules/c/ | B run／完整性、D 未結／履約 |
| D | feat/d-module | D | operator；收貨用 manager1 | http://127.0.0.1:5000/modules/d/ | B 庫存寫入、C 訂單工廠 |

以 C 為例，B／D 替換兩處字母：

```powershell
$env:APP_ENV='demo'
$env:MODULE_DEV='C'
.\.venv\Scripts\python -m flask --app wsgi seed-module C
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

停止伺服器後可執行基礎檢查及測試：

```powershell
.\.venv\Scripts\python scripts/check_module.py C
$env:APP_ENV='test'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m pytest tests/test_contracts.py -q
.\.venv\Scripts\python -m pytest -q
Remove-Item Env:APP_ENV
```

check_module 只用 Flask HTTP 測試客戶端，並非瀏覽器人工實測。C 的 seed-module 建立持久化受控 run／run_items，頁面列實際 ID，可供真實 C 草稿外鍵使用；D 建立明示 fixture_only 的測試訂單；兩者不代表 B 計算或 C 正式送單成功。B 自行實作真實庫存／計算，C 自行實作確認／送單，D 自行實作履約，另一人尚未合併不影響自己繼續01→05。

人工核對：登入後進入自己模組 URL → 顯示「非真實跨模組整合」及來源；C 飲料受控建議為30件、mu=20，direct 案例則為 null；D 顯示 FIXTURE 訂單原訂量30。錯誤路徑：開未啟用模組 URL →404；一般 demo 移除 MODULE_DEV 後替身入口404，未註冊服務503；禁止將開發替身當正式服務。API／DTO 正常與例外案例的可執行檢查見 tests/test_contracts.py。

業務實作放既定 models／services，自己模組的 routes.py 及 services.py.install() 已自動註冊。完整介面、欄位及鎖順序見 docs/contracts.md、docs/schema.md；更新自己 docs/handoffs/B.md、C.md、D.md。不要同改共用 app factory 或建立另一套訂單／庫存表。

## 空 test DB 重建檢查（選用）

只在自己的、確認沒有資料的獨立 test DB 使用：

```powershell
.\.venv\Scripts\python scripts/rebuild_empty_test.py --confirm-empty-test
```

此命令驗證本機 test DB 與所有資料表空白（除 alembic_version），再移除空 schema、從零 upgrade 並 check／heads；有資料立即拒絕。一般 pytest 不清 schema、不 drop_all，只回滾測試交易。基準採向前 migration；舊版自動產生的 downgrade 會遇到 MySQL 外鍵索引限制，不作資料回退保證，也不修改已發布 migration。資料恢復使用備份，新變更使用相容 revision。

## 本機 A 的隔離 MySQL 實例

前端事件測試已加入CI，本機可用 `node --test tests/ordering_ui.test.cjs` 重跑。真實Edge測試為選用：先以虛擬環境安裝 `python -m pip install playwright`，已有Microsoft Edge時不需下載瀏覽器；再執行 `.\.venv\Scripts\python.exe -m pytest -q tests/browser_ordering.py -p no:cacheprovider`。此檔案不包含在一般pytest；Playwright缺少時會跳過，不能記為通過。截圖保存於忽略的 `instance/browser-check/`。測試限定獨立test DB，不用demo測試。

本次自測另啟動 MySQL 9.6.0，僅綁127.0.0.1:3307，資料在忽略的 instance/mysql-data、程序識別在 instance/mysql.pid；與既有 MySQL96／3306服務分開。A 的 .env 已設定此實例及兩個獨立 DB，憑證未提交；B／C／D 應使用自己電腦的 MySQL 與各自 .env，不複製 A 的資料目錄。

A 重開電腦後需要啟動這個本機實例時：

```powershell
Start-Process -FilePath 'C:\Program Files\MySQL\MySQL Server 9.6\bin\mysqld.exe' -ArgumentList '--no-defaults','--basedir="C:/Program Files/MySQL/MySQL Server 9.6"','--datadir="C:/Users/user/Desktop/system2/instance/mysql-data"','--port=3307','--bind-address=127.0.0.1','--mysqlx=OFF','--log-error="C:/Users/user/Desktop/system2/instance/mysql.log"' -WindowStyle Hidden
```

若3307已在執行，不重複啟動。此環境為本機開發，不是部署。
