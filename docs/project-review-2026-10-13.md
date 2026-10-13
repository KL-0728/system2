# 全系統檢查與修正（2026-10-13）

身份A；範圍A04管理、A05真實整合、A06驗證及全系統補修。使用者明確授權納入起始的全部未提交修改，檢查、優化及直接推main。開發分支`chore/a-project-completion`，同步基準`b45cccb`，已fetch且確認origin/main包含於HEAD。沒有另改B/C/D分支、重寫歷史、修改spec或部署。

## 各視角的檢查與處理

| 視角／部分 | 核對項目及實際處理 | 驗證依據 |
| --- | --- | --- |
| 店長日常 | 庫存→建議→總覽→確認送單→訂單查詢→收貨；接入真實日常入口，維持一次逐單確認及重要例外 | test_confirmation、test_submission、browser_a_completion |
| 銷售／庫存 | 歷史與日常入帳分離、負帳面、延後盤點、修訂差額、來源唯一、報廢／退回、收貨原子性；當輪完整性改批次查詢 | test_sales、test_inventory、test_inventory_operations、test_integrity_batch |
| 補貨模型 | 七日窗口、精確箱入取整、null直接訂購、人工預測、容量、缺貨時序、固定B與截止；本輪政策更新重新生成 | test_replenishment、test_forecast_modes、test_management |
| 統家履約 | 接單／拒絕／變更／重申／取消、分批出貨／收貨、差異／补送／多送、U/C互斥；MySQL鎖後最新讀取及HTTP版本前置條件 | test_fulfillment、test_full_integration、test_fulfillment_concurrency |
| 管理者 | 真實商品／門市／帳號／政策／稽核／時鐘畫面；政策保存歷史、舊版本409，新商品空帳不能冒充核對盤點 | test_management、browser_a_completion |
| 身分／安全 | 後端角色／跨店／CSRF／生產模式；新增重設密碼撤銷舊登入，非法API參數與身分注入明確拒絕 | test_permissions、test_foundation、test_completion_review |
| 操作體驗 | 中文履約狀態／事件／待辦、台北時間；100張以上履約單可翻頁，重新整理保留已選單，避免非同步舊回應蓋掉新門市畫面 | browser_a_completion、既有全套browser測試及分頁API回歸 |
| 維護／效能 | 1000商品及14000歷史列真實計算、批次未結量、相容DTO；migration無新增差異、依賴檢查、Git差異檢查 | performance_integration、test_project_review、flask db check、pip check |

移除重複的時間格式脚本載入，集中共用版型；移除正式登入的種子／示範文案及README「管理尚未完成」舊說明；抽出重複履約門市驗證與共用分頁模板。保留稽核、不可變歷史、測試、合成種子與受限模組開發工具，它們有規格用途，未刪除失敗案例或業務資料。

## 真實範圍與限制

一般整合模式使用真實B/C/D提供者，新增閉環案例由C確認送單，沒有以工廠訂單替代正式送單。既有模組測試仍包含明示受控提供者／fixture訂單，它們只作各模組證據。新增分頁測試在test交易建立100個純查詢用訂單／草稿，不作真實送單證據、不改demo。

這是spec要求的可驗證Flask/MySQL原型。真實POS、物流、付款、正式公司帳號、近千店上線和外部部署不在本版範圍。三位真人逐人兩分鐘／零口頭協助、完整人工V驗收及影片上傳仍待團隊實際完成，不能用AI瀏覽器結果代填。

## 組員操作與預期

先在根目錄停止舊Flask，保留`.env`與資料；依README啟動既有MySQL，執行`python scripts/check_environment.py`兩個DB均PASS後，以`APP_ENV=demo`且清除`MODULE_DEV`啟動Flask。完整PowerShell命令、案例及數字見[a-completion-testing.md](a-completion-testing.md)。

1. 開 http://127.0.0.1:5000/login，使用本機示範帳號及當初建立帳號的密碼；升級後須重新登入。manager1／manager2先查`/api/auth/me`確認門市，再核對跨店API404。
2. admin維護商品／政策；兩個分頁修改同筆資料，後儲存舊版本409。新安全庫存只影響新計算，歷史訂單快照維持。operator／manager1直接開`/admin`應403。
3. 另一視窗登入一個測試店長，admin替該帳號重設密碼；原視窗`/api/auth/me`應401，舊密碼拒絕、新密碼成功。勿用真實密碼測試；若替自己的admin改密碼，自己也須重新登入。
4. 用BCDEMO/bcmanager完整走建議→確認→送單→operator接單／出貨→bcmanager收貨。初始有效庫存20、原訂30、可售實收28及損壞2，預期實體50／不可售2／可售48；重送不加第二次。若已操作過，先核對當下資料，不能假設仍是初始案例。
5. 訂單明細應顯示中文狀態／核對收貨事件／待辦與台北時間；履約清單有100張以上時下一頁能查看舊單。手機390／320px核對無橫向溢出。
6. 錯誤回報附實際main SHA、角色、步驟、預期／實際數字及錯誤文字，遮蔽憑證。直接API需CSRF及expected_version；缺漏欄位422、非法查詢400、舊版本409。

本次發布依使用者直接授權執行；實際版本可執行`git log -1 --oneline main`、`git rev-parse origin/main`與`git status --short --branch`核對。現在團隊可依以上步驟實測並填真人驗收，無須另授權本次發布。

## 本次實際驗證

- `python -m pytest tests -q -p no:cacheprovider --tb=short` 的最終後端集合：**383 passed / 199.61s**，沒有warning。原執行命令另列browser及performance路徑，但pytest與`tests`目錄去重時只收集383個後端案例，已以collect-only核對，因此瀏覽器及效能另行執行、分開記錄。
- 新增安全／查詢／輸入案例及管理／閉環首輪：39 passed、2 failed；失敗來自新增Edge斷言抓到時間軸仍輸出英文事件，修正實際前端後Edge管理及真實閉環 **5 passed / 17.27s**。没有刪除斷言或業務案例。
- `node --test tests/ordering_ui.test.cjs`：**2 passed**；orders.js／fulfillment.js／management.js語法檢查、Python compileall及git diff --check通過。Git的LF→CRLF提示不是差異錯誤。
- `APP_ENV=test flask db check`：No new upgrade operations detected；`flask db heads`：單head `884e7a53a8c8`。`pip check`：No broken requirements。開始前demo/test都經唯讀環境檢查PASS，沒有初始化或重建DB。
- 全部52個Edge案例及1000商品效能：**53 passed / 168.68s**，沒有skip或warning。指令為`python -m pytest tests/browser_a_completion.py tests/browser_forecast_modes.py tests/browser_fulfillment.py tests/browser_fulfillment_full.py tests/browser_inventory.py tests/browser_inventory_operations.py tests/browser_ordering.py tests/browser_project_review.py tests/browser_provider_integration.py tests/browser_replenishment.py tests/performance_integration.py -q -p no:cacheprovider --tb=short --junitxml=instance/final-review-browser.xml`。Edge管理1280／390／320px及真實閉環1280／390px包含中文訂單明細；其他模組Edge證據仍依各檔案來源區分。
- 1000商品／14000歷史列使用本機MySQL9.6／Python3.12及真實提供者，生成低於測試所要求5秒（性能斷言通過）。本次命令未加`-s`，不另填未保存的精確生成秒數；不是正式近千店壓測。
- 兩組共**436個Python案例**及**2個Node案例**通過；完整瀏覽器測試包含既有模組受控資料，不能將436項全部說成真實端到端案例。測試用獨立test DB，demo及本機設定保留。
