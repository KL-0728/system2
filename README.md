# 統家便利店補貨系統

本文件是唯一的首次安裝、日常啟動、升級、測試及故障排除入口。產品以 [spec.md](spec.md) 為準，四人協作依 [agent.md](agent.md)。完整操作與人工驗收見 [2026-10-14 修正報告](docs/system-hardening-2026-10-14.md)。

六項複查的原因、修復、回歸結果與逐步實測見[六項複查交接](docs/six-review-fixes-2026-10-14.md)。草稿封存／重建先選擇儲存或放棄；權限失效保留原履約請求，可恢復後以原內容重試；管理刷新失敗時使用「重試載入設定」。

系統使用真實 B 庫存／七日平均、C 草稿確認送單、D 接單出貨收貨。課程資料為合成資料，不宣稱企業效益；未實作總倉配貨、付款、真實 POS、外部物流、完整效期批次或大型分散式架構。真人計時及影片由組員執行。

## 首次安裝（PowerShell）

需求：Python 3.12、MySQL 8.4以上；Node用於前端測試。各成員使用獨立checkout、demo與test DB，不共用錄影資料。

```powershell
git clone https://github.com/KL-0728/system2.git
cd system2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

由本機DB管理者建立 `system2_姓名_demo`／`system2_姓名_test`（utf8mb4／InnoDB），授予只限兩庫的應用帳號權限。在`.env`填`DATABASE_URL`、`TEST_DATABASE_URL`、至少32字元的`SECRET_KEY`、至少8字元的`DEMO_PASSWORD`。不得提交`.env`、備份或憑證。產生SECRET_KEY及首次初始化：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db upgrade
$env:APP_ENV='demo'
.\.venv\Scripts\python.exe -m flask --app wsgi db upgrade
.\.venv\Scripts\python.exe -m flask --app wsgi seed-demo
```

`seed-demo`只用於首次空demo DB，有資料拒絕覆蓋。帳號為`manager1`／`manager2`／`operator`／`admin`，密碼取自建立種子時本機`DEMO_PASSWORD`。修改`.env`不會自動修改既有帳號密碼。

## 日常啟動及升級

先啟動`.env`指向的既有MySQL，保留資料。A此checkout使用3307時可執行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_a_mysql.ps1`；其他組員啟動自己的服務。[個別電腦與舊流程](docs/archive/readme-before-2026-10-14.md)僅供追溯。

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
```

若migration落後，先停止Flask，依[備份還原流程](docs/backup-restore.md)備份，再升級兩個資料庫。新版相容migration head為`a1410260003`，保留原訂單、庫存、示範時鐘及歷史快照；勿修改已發布migration。

```powershell
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db upgrade
$env:APP_ENV='demo'
.\.venv\Scripts\python.exe -m flask --app wsgi db upgrade
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

開啟 http://127.0.0.1:5000/login。一般整合使用空`MODULE_DEV`，不得將模組替身當真實閉環。示範起始時間為2026-10-08台北21:00，admin可向前推進示範時鐘；正式模式禁止調整。每天21:00–22:00可盤點／計算／送單，配送輪次自動準備；其他時間可查資料及收貨。閒置30分鐘須重新登入，工作恢復後仍須通過版本、權限及確認。

## 測試

先確認環境檢查PASS，一次只執行一組使用同一test DB的測試。交易、併發、冪等及出收貨使用MySQL，不回退demo或SQLite。

```powershell
$env:APP_ENV='test'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --test tests/ordering_ui.test.cjs tests/recovery_ui.test.cjs
.\.venv\Scripts\python.exe -m flask --app wsgi db check
```

瀏覽器需另安裝Playwright，本機使用Edge；CI使用Chromium執行真實B／C／D正常閉環。缺依賴的skip不算通過。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe -m pytest -q tests/browser_a_completion.py tests/browser_system_hardening.py tests/browser_six_review.py -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -s tests/performance_integration.py tests/performance_open_history.py -p no:cacheprovider
Remove-Item Env:APP_ENV
```

空庫重建只用於另建、確定空白的獨立test DB：`python scripts/rebuild_empty_test.py --confirm-empty-test`；非空會拒絕。備份／還原使用[backup_database.py](scripts/backup_database.py)，`reset-demo`會刪除示範資料，不能當還原。

## 故障排除

| 現象 | 處理 |
| --- | --- |
| MySQL2003／拒絕連線 | 啟動`.env`指定服務與連接埠，再跑環境檢查；不覆寫設定或初始化既有資料 |
| migration落後／缺round或fulfillment_commands | 停止Flask、備份、兩個APP_ENV分別db upgrade，再啟動 |
| 登入密碼不符 | 確認建立帳號時密碼，由admin保留資料改帳密，不reset-demo |
| 401／閒置逾時 | 重新登入原身份返回原頁；原請求與草稿仍須通過權限與確認 |
| 結果不明／網路中斷 | 保留瀏覽器本機儲存，使用「以原內容重試」或查詢原訂單，不改內容另送 |
| VERSION_CONFLICT | 更新資料，核對異動並重新計算／預覽；不能沿用舊勾選 |
| 缺銷售／無有效盤點／負帳面 | 按缺口日期補銷售入帳，完成盤點或對帳；人工需求不能繞過庫存保護 |
| 21:00前／22:00後不能送單 | 看台北下一次開放時間，等下一輪重新計算；不繞過正式時鐘限制 |
| 看不到新版介面 | 停止舊Flask、重啟、Ctrl+F5；勿同時啟動多份同連接埠 |

組員開發、模組替身、PR及歷史交接看[團隊操作入口](docs/team-start.md)、[合約](docs/contracts.md)、[驗收證據](docs/acceptance.md)。本次A已獲授權完成後推送main；B／C／D仍在自己的分支交PR，由A審核合併。不得force push或改寫他人分支。
