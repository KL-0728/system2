# B／C提供者整合修正與D接入防護

2026-10-11；A修正分支 fix/a-provider-integration，起始 main=527ba2e（B PR #3），合約 v1／spec v1.4不變。使用者已授權自測完成後提交、合入main及推送；不部署。

## 修正的行為

- 共用「缺服務」測試明確移除插槽，不假設B／C／D永久尚未實作；仍驗證503、production禁止替身與工廠。
- C首頁、工作台、dashboard及模組檢查頁依實際provider選相容快照。正式B選sma7-periodic-v1，不選工廠或受控資料；兩種來源共存也不互相遮蔽。沒有正式資料時顯示「準備補貨建議」，GET不建立假資料或新快照。
- 舊草稿保留，讀取顯示來源不可用及重新建立指引，修改／預覽／新送單返回DRAFT_SOURCE_UNAVAILABLE。既有成功送單重試的優先順序不變，不改冪等或確認規則。
- 正式訂單API及決策查詢排除fixture_only。D開發工廠服務仍可依原合約在明示開發模式使用。履約檢查依本門市正式訂單取ID，不硬傳1或其他門市ID。
- 模組檢查頁顯示每個provider的真實／受控來源。C seed-module在正式B已接入時不再追加受控快照；B、C、D原有正式註冊不會被測試注入覆蓋。
- 新增prepare-ordering-demo，以獨立BCDEMO門市／bcmanager準備正式B快照；合成期初40件、六日歷史與本日日常20件入帳、21:00正式盤點20件，再正式生成。外部D若受控則明示，不把來源叫做正式閉環。

沒有新增schema、migration、依賴或產品規格。既有快照、草稿、訂單與庫存不刪除、不改標來源；不修改.env、其他帳號密碼或業務時鐘。

## AI自測與限制

Python3.12／本機MySQL9.6 InnoDB 3307；system2_a_demo與空system2_a_test分離，migration884e7a53a8c8。測試用test外層交易回滾，不清demo。

- 新增提供者交接回歸：18 passed，涵蓋來源混合／缺資料／舊草稿、正式API拒絕工廠、真實B caller rollback／重試、舊替身結果拒絕、示範準備冪等，以及提供者切換後新送單拒絕／既有成功送單重試。
- node --test tests/ordering_ui.test.cjs：2 passed。
- 完整pytest：323 passed in 154.58s；1個PytestCacheWarning（.venv/Lib/site-packages/_pytest/cacheprovider.py:469，Windows拒絕建立.pytest_cache/v/cache/nodeids，WinError5）。僅本機pytest快取寫入警告，保留原權限；測試本身全部通過。
- 實際demo新增BCDEMO id5、正式B快照#7、bcmanager；再次執行保留原結果。比對所有原有門市／庫存版本與業務時鐘均不變。
- Edge真實瀏覽器：23 passed（新來源案例12、原C工作台11）；1280/390/320px、20px字體、空來源／舊草稿／正式快照／舊草稿快取均通過，沒有橫向溢出或頁面JavaScript錯誤。
- 這不是D正式收貨驗收，正式D尚未接入；D所有履約／分批收貨／補送／真實closed-loop／V01–V50仍待A05／A06。人類B／C／D實測不代填。

## A可照做的實測

在C:\Users\user\Desktop\system2，停止舊Flask終端（Ctrl+C），另開PowerShell：

```powershell
$env:APP_ENV='demo'
$env:MODULE_DEV='C'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi prepare-ordering-demo
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

1. 環境應兩行PASS；prepare指令目前應顯示BCDEMO id5已存在且保留。只允許本機system2_*_demo、MODULE_DEV=B/C與21:00–22:00示範業務時間，不自動改時鐘。
2. 開 http://127.0.0.1:5000/login，登入bcmanager，密碼取本機.env的DEMO_PASSWORD（新帳號建立時值，勿貼聊天）。同一視窗 http://127.0.0.1:5000/api/auth/me 應username=bcmanager、stores含BCDEMO id5。
3. 開 http://127.0.0.1:5000/store/ordering?store_id=5，確認首次說明後看商品。飲料H20、七日平均20、L1、SS10、無未結量時建議30；可以建立草稿、預覽。D來源仍受控，不能把這當正式供貨證據。
4. 用既有manager1（密碼沿用原本機值）查看DEMO1的工作台：若只有假快照，應顯示準備指引而不是422/409。舊受控草稿連結仍能開啟，明示原草稿保留、不能繼續預覽；不要把舊草稿內容自動搬到新快照。
5. 開 http://127.0.0.1:5000/modules/c/：runs/integrity真實，D缺項受控；沒正式快照時顯示指引，不硬呼叫ID0。320/390px或125%字體應無頁面橫向溢出。
6. demo準備指令重跑不改既有數量、密碼或時鐘。test／production環境應拒絕。紀錄任何失敗的身份、網址、版本與錯誤；不重設或清除既有錄影資料。

## D提交前核對

D同步本修正後保留自己的任務分支與工作。獨立測試可明確注入ControlledInventoryWriter驗rollback，真實接入必須換回正式B並使用同session。正式入口排除fixture_only；新D來源與舊替身資料共存時不得把替身result冒充正式入帳。共用自測：

```powershell
python -m pytest tests/test_contracts.py tests/test_provider_integration.py -q
```

再跑D自己的履約與MySQL併發測試；A在獨立整合分支驗正式C送單→D收貨→B庫存。所有來源核對、失敗rollback與同鍵重試通過後才合併，不bypass失敗CI。
