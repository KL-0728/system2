# D 履約模組人工實測

這份指引供 D 自己的 `feat/d-module` checkout 使用。目前程式未提交；Git HEAD 是 `9cf5d00` 加本機修改。2026-10-12 已建立 D 專用 MySQL demo／test，環境檢查與 D 模組自動測試通過；Edge 自動瀏覽器測試已驗接單、出貨、分次收貨與手機寬度，下列完整瀏覽器操作仍未由人類實測，不可記作通過。不要使用 A、B、C 的資料庫，也不要重設已有操作或錄影資料。

## 1. 準備獨立環境

在 `C:\Users\88697\Downloads\Github\system2` 的 PowerShell 執行。若已建立 D 專用 `.env` 與資料庫，略過建立、seed 步驟，先跑唯讀環境檢查。`.env` 依 README 指向 `system2_d_demo` 與 `system2_d_test`，密碼留在本機，不貼到聊天。新 DB 才執行：

```powershell
$env:APP_ENV='test'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
$env:APP_ENV='demo'
$env:MODULE_DEV='D'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m flask --app wsgi seed-demo
.\.venv\Scripts\python -m flask --app wsgi seed-module D
.\.venv\Scripts\python -m flask --app wsgi fulfillment prepare-demo
.\.venv\Scripts\python scripts/check_environment.py
```

預期 demo／test 皆 PASS。`prepare-demo` 只在 D 專用 demo DB 初始 2026-10-08 21:00 且尚未推進時，將示範時間推至 21:01，讓收貨時間晚於種子盤點；同時補齊尚未回覆的 D 測試訂單待辦，不覆寫既有待辦。`seed-module D` 產生兩店各一張 `FIXTURE` 訂單，原訂量 30 件，只供獨立 D 開發，不代表 C 正式送單。若 DB 已有資料，勿重新 seed 或 reset。

在同一終端機啟動 Flask：

```powershell
$env:APP_ENV='demo'
$env:MODULE_DEV='D'
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

所有網址使用 `http://127.0.0.1:5000`。新 demo 帳號為 `operator`、`manager1`、`manager2`；密碼取自你自己的 `.env` 中 `DEMO_PASSWORD`。既有 DB 不會因修改 `.env` 自動改密碼。每次換身份先登出，在同一瀏覽器視窗開 `/api/auth/me` 確認 `username`，再看 `stores` 內的門市 id；最外層 `id` 是帳號 id。

## 2. DEMO1：正常、分次、損壞與補送

1. 以 `operator` 登入，開 `/headquarters/fulfillment`，選 DEMO1 與 `FIXTURE` 訂單。預期頁面明示測試訂單、原訂 30 件、狀態 `SUBMITTED`，並顯示接單待辦與期限。
2. 在「完整接單」填承諾 30 件，沿用表單預填的要求 ETA，送出。預期 `ACCEPTED`，未出貨承諾 30；重複點擊期間按鈕停用。
3. 在「出貨」填 5 件並送出。預期批次出貨 5，待核對 5，原承諾尚有 25 未出貨。若輸入 31 件，預期拒絕且沒有新增批次。
4. 登出，以 `manager1` 登入，先確認 `/api/auth/me` 是 DEMO1，再開 `/store/receiving`，選同訂單。預期本批預填核對 5、可販售 5；預填本身尚未改庫存。
5. 將本次核對量改 2、可販售改 2，損壞與短收留 0，確認。預期本批已核對 2、仍待核對 3；在另一頁開 `/store/data` 查同商品或讀 `/api/inventory/status`，帳面實體由 20 至 22、可售由 20 至 22。餘下 3 是「待收」，不可自動當短收。
6. 核對剩餘 3：可販售 2、損壞 1、短收 0，原因填「包裝破損」。預期出貨批次待核對 0，損壞差異 1；帳面實體 25、不可售 1、可售 24。
7. 登出，以 `operator` 回到同訂單，對損壞差異授權補送 1。預期顯示單獨補送授權；同差異再授權 1 應拒絕，不能超過案件額度。
8. 用「補送出貨」發 1，預期 `replacement` 批次 1；原始累計出貨仍是 5，此批有獨立授權 id。登出，`manager1` 核對補送 1 可販售，預期帳面實體 26、不可售 1、可售 25。
9. `manager1` 對原損壞差異選報廢 1，預期帳面實體 25、不可售 0、可售仍 25；原收貨紀錄保留。第二次用新請求再報廢 1 應被拒絕。對同批輸入超過待核對量或 0，也應被拒絕且庫存不變。

庫存數字以新建、未做其他操作的 D demo DB 為前提；既有 DB 請先記錄該商品操作前的帳面值，以差額比對。等待回應時不要自行產生新的請求鍵重送；若結果不明，先刷新訂單、出貨批次、收貨與庫存紀錄。

## 3. DEMO2：提案、爭議、待查與權限

1. `operator` 選 DEMO2 的另一張 `FIXTURE` 訂單，提出新承諾 20 件及較晚 ETA，填寫原因。預期狀態 `CHANGE_PENDING`、原請求 30 仍顯示，提案量不冒充已承諾。
2. 登入 `manager2`，確認 `/api/auth/me` 的本店是 DEMO2；在 `/store/receiving` 同訂單回覆接受。預期承諾 20、原訂仍 30、差額 10 明確結束。重複回覆應返回衝突，不再改量。
3. `manager2` 提出取消未出貨量並填原因；`operator` 可回覆，提案本人不可自己回覆。若 `operator` 拒絕，原承諾仍在但有爭議；再用「重申原承諾」解除爭議後才能新出貨。接著出貨 2。
4. `manager2` 可把待核對 2 標記「到貨待查」，預期仍待收 2，但來源列 `RISK`，不作有效 C 扣抵。`operator` 填新 ETA 和確認結果，預期待查結束；若 ETA 合法且尚在保護期才可能恢復 C。若已明確短收，應在收貨核對輸入短收量，退出原在途並新增差異，不能同時算待收與補送。
5. `manager2` 用該出貨批次的「登記隔離多送品」選另一商品與 1 件，填原因。預期時間軸出現 `EXTRA_HELD`、統家有處理待辦，而該商品庫存完全不變；`operator` 選退回或報廢並填原因後，預期出現 `EXTRA_RESOLVED` 且待辦結案。不要把多送品當正常收貨入庫。
6. `manager1` 嘗試讀 DEMO2 訂單詳情，預期 404；`manager1` 開 `/headquarters/fulfillment` 預期 403；`operator` 開 `/store/receiving` 預期 403。未登入讀受保護 API 預期 401。
7. 在 manager 的收貨頁建立「聯絡統家」待辦並填原因，預期有期限與逾期標示；填處理結果後才結案。僅時間到期不會自動收貨、同意提案或取消訂單。

## 4. 自動檢查與回報

停止 Flask（Ctrl+C），切到 test DB 執行：

```powershell
$env:APP_ENV='test'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python -m pytest tests/test_fulfillment_rules.py tests/test_fulfillment.py tests/test_contracts.py tests/test_provider_integration.py -q
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m flask --app wsgi db check
```

測試只使用 D 自己的 `system2_d_test`；無 `.env` 或 MySQL 時不要把「測試已收集」寫成通過。請記錄每項的指令、passed／failed、warnings 類型與訊息。人工回報請附分支、HEAD SHA、未提交狀態、所用 DB 名稱（不含密碼）、實際帳號與門市 id、步驟、預期與實際庫存數字，以及錯誤畫面；手機再各走接單與收貨一次。不要貼憑證。

若有失敗，先回報「D 模組實測第 N 步失敗：預期…，實際…，錯誤…，分支…」，修正後只重測受影響步驟及相關自動測試。全部結果確認後，再依 agent.md 第5.5節提交、推送並開交給 A 的 Ready PR；人工實測未完成時只能標示 Draft，不可宣稱 Ready。
