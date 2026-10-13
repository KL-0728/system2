# 營運工作區、登入與全畫面檢查（2026-10-13）

身份A，範圍為全專案版面、日常操作文案、密碼顯示及實際預覽。使用者追加授權「優化完直接推上main，推上之前再進行一次完整檢查」。開發分支 `feat/a-operations-ui`，乾淨同步基準 `171d33f`，fetch／pull --ff-only成功。沿用既有服務、帳密及資料，未改產品規格、資料表、migration或依賴，沒有部署外部網站或啟動AI子代理。

## 實際參考及改動

參考 [Odoo Inventory 的每日營運待辦總覽](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/warehouses_storage/reporting/dashboards.html)與 [SAP Fiori 的明細頁結構](https://experience.sap.com/fiori-design-web/object-page/)，採用工作區導覽、作業摘要、明確主操作及展開式明細。這是對既有規格的介面改良，沒有宣稱提供Odoo／SAP全部功能或真實POS／物流串接。

| 頁面／部分 | 本次處理 |
| --- | --- |
| 登入 | 完整品牌／作業流程區與登入卡片，手機上下排列；帳號密碼、錯誤、協助及「顯示／隱藏密碼」有清楚位置；保留首次登入及重新登入安全行為 |
| 全站工作區 | 白色標頭、角色及帳號、桌面側邊導覽／窄畫面橫向導覽、目前門市、選中頁狀態及鍵盤跳到內容；統一卡片、字級、欄位及按鈕 |
| 營運首頁 | 由真實訂單、草稿及待辦取得摘要，店長只看本店、供貨人員看啟用門市；未用裝飾數字或示範KPI代替查詢 |
| 資料管理 | 卡片密度、桌面表單分欄及手機單欄；CSV格式及範例收合，明示範例不是實際銷售資料，不引導直接提交假銷售 |
| 補貨計算 | 配送／歷次建議兩組控制、中文作業文案，技術版本及公式放進明細；正常畫面不再顯示OpenOrdersService／B03案例等開發資訊 |
| 訂購與確認 | 桌面商品欄對齊、手机卡片；一般理由預設收合，數量或理由有修改時自動展開；重要風險、例外確認及每單確認保留；首次說明按鈕等腳本就緒後才可點擊 |
| 訂單明細 | 使用共用工作區、標題／分區／歷史決策卡片，保留原訂量、履約狀態及時間軸 |
| 接單／收貨 | 門市與訂單篩選列、分頁、統一表單及手機版，移除正常訂單的「正式送單」開發標籤，保留fixture訂單的測試標示 |
| 管理 | 分類選中狀態、名單／編輯分欄、手機單欄及有限高度名單；配送與示範設定收合；維護命令留文件，帳號密碼切換保留 |
| 快取／預覽 | CSS／JS網址帶內容指紋，動態HTML與API禁止快取；實際重啟舊Flask程序，核對使用者原5000網址回傳新版 |

「示範環境／示範時間」依spec保留在精簡環境列；正式環境不顯示。明確啟用MODULE_DEV時的受控測試標示保留，不能把替身包裝為真實營運資料。主要變更集中於base、home、auth/login、operations.css及各模組模板；API／DTO／確認文案版本、公式、警示分級及庫存交易不變。

## 預覽問題與處理

初次檢查 `http://127.0.0.1:5000/login` 回200，但HTML沒有現有main的密碼按鈕，證實是舊伺服器回應。其後發現同一專案另有殘留Flask父／子程序，共用5000會造成新舊版混用與500。以唯讀方式核對程序工作目錄都為本checkout後，僅停止本專案的舊Flask並重啟，不停止其他Python、MySQL或清資料。

最終原5000網址回 **200**，HTML包含 `auth-layout`、`data-password-toggle`、內容指紋資產，並回 `Cache-Control: no-store`。排查時的獨立5001預覽已停止。維護時只啟動一份Flask；若使用者仍開舊畫面，先Ctrl+C停止自己舊終端機程序再重啟，勿反覆啟動多份佔用同一埠。

## 完整自測

環境：Windows 11、Python3.12.6、MySQL9.6／3307，獨立 `system2_a_test`，各測試交易回滾；既有demo保留。環境檢查demo／test皆PASS，migration head `884e7a53a8c8`。

- 完整後端 `python -m pytest -q -p no:cacheprovider`：**398 passed／198.25秒**。包含真實B→C→D→B、權限、確認／版本／冪等、交易／併發及新增首頁隔離／資產／密碼測試。
- Node `node --test tests/ordering_ui.test.cjs`：**2 passed**，保留空值阻止寫入及排除後重新預覽的事件驗證；新增DOM收合節點支援。
- `flask db check`：無新增結構差異；`db heads`：單head；`pip check`、compileall、JS語法及git diff --check通過。
- Edge全畫面檢查：1440／390／320px，涵蓋登入、三角色首頁、資料、計算、訂購、訂單／明細、收貨、履約及管理商品／帳號／政策；畫面摘要由真實C送單取得，沒有使用工廠訂單作此證據。截圖在忽略的 `instance/browser-check/operations/`，已檢視桌面登入／首頁／訂購及手機登入／收貨／政策。
- 12檔完整瀏覽器回歸最終 **62 passed／186.25秒**；涵蓋上項外，還有20px文字放大、空值、特殊大量、排除、跨分頁、網路重試、完整出貨／分次收貨／差異等。開發模式測試的受控來源另有明示，不能作真實閉環證據。
- 規模自測 **1 passed**：1000商品／14000歷史列真實計算 **1.090秒**，庫存狀態查詢 **0.119秒／10 SELECT**。這是本機合成資料量測，不代表外部正式服務效能。

可重跑完整檢查（先check_environment，使用獨立test DB）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q tests/browser_operations_ui.py tests/browser_audit.py tests/browser_a_completion.py tests/browser_ordering.py tests/browser_inventory.py tests/browser_inventory_operations.py tests/browser_forecast_modes.py tests/browser_replenishment.py tests/browser_fulfillment.py tests/browser_fulfillment_full.py tests/browser_provider_integration.py tests/browser_project_review.py -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -s tests/performance_integration.py -p no:cacheprovider
node --test tests/ordering_ui.test.cjs
```

預期分別398、62、1、2項通過。Playwright／Edge缺少時的跳過不記為通過；尚未實際執行的真人計時亦不代填。發布提交及main／CI實際結果以本次交付回覆、Git提交及GitHub檢查紀錄確認。

檢查過程未掩蓋失敗：文案改善後，原測試仍等開發用語而失敗，已對齊操作文字、以可見警示及data-warning-code／level保留判斷；新增全畫面測試首次定位到收合的選項卡，改定位實際結果；完整回歸另發現1024px欄位對齊及首次說明腳本載入競態，已修正後重驗。不刪測試、不移除警示／確認或降低權限要求。

## 團隊人工核對

目前由AI完成全套檢查及發布；發布後可直接開 http://127.0.0.1:5000/login 並Ctrl+F5。帳號manager1／manager2／operator／admin，密碼仍取本機.env的DEMO_PASSWORD，不用重設或seed-demo。

若自行重新啟動，先停止自己原Flask終端機，再在專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
$env:APP_ENV='demo'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

1. 登入頁→品牌與登入卡片完整顯示，顯示／隱藏密碼不改內容；錯密碼回同頁、保留帳號並清空密碼，正確重試可登入。
2. manager1→首頁顯示本店作業摘要、補貨／訂單／收貨／資料管理導覽；manager2只顯示自己的門市，無管理設定入口。摘要為實際資料，沒有資料時顯示0及空狀態。
3. 補貨頁→「產生補貨建議」「查看當時建議」，沒有提供者名稱或B03案例文案；資料時間與版本可展開。缺口、負帳面、過期與重要提醒仍不能略過。
4. 一般訂購→理由預設收合；調整一箱後自動展開，填原因並儲存，預覽前後調整保留；重要例外直接可見且未確認不能送出，正常單仍只一個逐單確認。
5. operator→營運待辦與接單履約；選門市／訂單能接單、出貨；manager1→核對收貨，預填不等於已入庫，確認後才更新。實際寫入請用自己的demo案例並記下前後數量。
6. admin→管理分類、名單及編輯；名單可捲動，帳密欄可切換顯示，儲存途中仍停用；展開配送或示範設定才顯示相關工具。未授权角色後端仍403，合法他店ID對店長404。
7. 390／320px及125%文字放大→主內容無橫向溢出、checkbox與長文字可閱讀、按鈕可操作；1024px桌面商品欄位對齊。失敗回報角色、版本、畫面／步驟及預期差異，不附密碼。

完整真人三人計時與影片仍須團隊實際執行，本次自動瀏覽器檢查不代填真人驗收。發布採已授權的main更新，保留必要CI及歷史，不force push或部署。
