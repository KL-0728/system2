# B 模組交接

本次只授權 **B03**，沿用已提交的B01／B02。B03已實作及自測，完成後停止；不進B04、不commit、不push、不開PR、不合併main。現在請B依[B03畫面核對指南](../b03-manual-testing.md)實測；以下AI證據不代填人工或產品驗收通過。

- 分支：feat/b-module；開工乾淨；git fetch origin --tags、git pull --ff-only成功（Already up to date）。
- 遠端：https://github.com/KL-0728/system2；HEAD／個人上游 5ca02631e02212826d2e923d30fb1c11077f14a0（b2 complete）。B01 a139a7a及B02由組員先前提交／推送，本次AI未執行發布。
- 基準：origin/main f2d5f67452ac249fe14a979a1433d69fa2802236及a03-parallel-v2 1744fbd01446597b3be6c552b991476d86950b75，祖先檢查均結束碼0；沒有新增main需要合併。
- 被測版本：5ca0263＋本機未提交B03修改。合約v1、spec、schema、migration head 884e7a53a8c8均不變；不修改A／C／D檔案或凍結消費端測試。
- 正式B提供者：inventory_writer／integrity／runs。B03使用相同呼叫端session，不commit／rollback；生成只保存不可變run／品項／稽核，不改庫存或門市計算版本。缺D來源503，不默默回退。
- 開發界線：MODULE_DEV=B的open_orders為ControlledOpenOrders；正式B公式／H／快照不是替身。分段來源真實唯一性及真實履約留A05；完整產品V驗收留A06。
- 環境：Windows／Python3.12／MySQL9.6 InnoDB，B專用127.0.0.1:3308/system2_b01_demo及system2_b01_test。既有3306、.env及他人資料未修改。
- 本次新增持久化合成B03DEMO（id3）／b03manager，密碼沿用本機DEMO_PASSWORD。保留DEMO1／DEMO2活動，不改密碼／時鐘。業務時間2026-10-09 21:20，已用真實Edge保存B03快照#1並試算；全部既有門市版本、庫存數量／版本、時鐘前後相等。prepare-b03-demo重跑只保留原資料。
- B01人工歷史：2026-10-11，B回報「70 passed in 48.61s」，保留為組員重跑通過；未擴大解讀成瀏覽器或產品驗收。
- B03目前限制：完整回歸仍有兩項共用測試失敗，原因與協調項目如下，不宣稱全套綠燈。B03核心、畫面及最小真實B→C草稿讀取已驗證；不改合約遷就測試。

| 階段 | 改動 | AI測試／版本 | 人工結果 | 下一步 |
| --- | --- | --- | --- | --- |
| B01 | 同交易庫存異動、來源唯一與重試、盤點差額／不可變修訂、H與入帳阻擋 | 前次全套121 passed；B＋合約70 passed；數字核對PASS；f2d5f67＋當時未提交修改 | B回報70 passed in 48.61s；其餘未回報 | 已由組員提交a139a7a，沿用 |
| B02 | CSV整批驗證／提交／更正、歷史轉日常、防重扣、盤點／修訂畫面及回應遺失恢復 | 前次全套173 passed in 155.69s；真實Edge6 passed in 28.00s；a139a7a＋當時未提交修改 | 畫面人工結果尚未回報 | 已由組員提交5ca0263，沿用；保留前次證據 |
| B03 | 七日品質／Decimal輸出／精確整箱、固定B及L、U/C/RISK、雙版時序／容量、不可變run查詢／明細、v1 runs註冊及畫面 | B03新增48例通過；全套219 passed／2 failed in 146.51s；Edge9 passed in26.29s；demo Edge PASS；5ca0263＋未提交B03 | 待B照B03指南實測 | 停在B03；兩個共用舊假設請A協調；不發布、不進B04 |
| B04 | 未開始 | 未執行 | 未執行 | 本次不授權 |
| B05 | 未開始 | 未執行 | 未執行 | 本次不授權 |

## B03 改動與證據

- app/services/forecasting.py：七日需求、R1／有效輪次L、固定SS、U/C扣抵與向上整箱；用整數分子／分母保存精確整箱邊界，以固定60位Decimal輸出及JSON字串，無float需求運算。有效全零仍計算SS，零需求不強配箱。丟失銷量不形成欠貨。
- app/services/replenishment.py：七個固定連續營業日，不略過缺檔／缺貨／未正常營業；品質無效或H不可用時模型量與建議均null。保存七日日期／營業／缺貨、盤點／入帳來源／缺口、政策版本及參數、人工欄null、來源、公式、警示和曲線。超技術上限保留null與阻擋，不截斷。
- 同一交易按門市鎖與商品順序讀取有效庫存，核對D回應的門市／版本／時間／商品／來源唯一性／合法分桶。U未承諾與RISK事實可見；期外未結仍列未來預覽，逾期來源不虛構新ETA或加回H。
- 時序固定B逐日21:00先銷售、後到貨；已承諾＋候選與含待接單／風險＋候選分開。到貨前缺口、到貨後容量與最終數量重新試算；容量不直接H+Q，不縮量。risk_evaluated_at及配送輪次改變重新讀來源及重算L，不覆寫歷史run。
- 使用既有ReplenishmentRun／RunItem及共享不可變守衛，不改模型欄位／schema／migration。Numeric欄位作儲存索引值，v1讀取以快照保存的Decimal字串為準，避免12位欄位截精度後再算。
- app/modules/inventory/replenishment_routes.py、services.py、routes.py：POST/GET /api/replenishment/runs、context及試算API；店長／admin、跨店、CSRF、版本與截止驗證；正式runs供C使用。/store/replenishment為B03畫面，/store/data增加返回計算入口；自己的模板／CSS／JS，不改共用base或C頁。
- app/modules/inventory/replenishment_demo.py：只新增獨立B03合成門市／帳號／政策／三個商品的歷史資料／已核對合成庫存／三輪配送；資料不足案例刻意缺一日。明示合成，不冒充正式盤點／D履約；重跑不重設。
- tests/test_replenishment.py：48例，涵蓋規格30件、29取30、充足H為0、全零、缺檔／缺貨／閉店／錯區間、H缺口／負值／對帳、來源場景／錯誤／唯一性、期限等於到點、L1/L3、2140固定B、22:00截止、容量、非法整箱／技術上限、快照不可變／回滾、權限／CSRF、呼叫端Decimal精度及C讀真實run／建測試草稿。後者只證明最小相容，不代表正式整合全部通過。
- tests/browser_replenishment.py：真實Edge桌面1280、手機390／320、20px文字無頁面橫向溢出；展開七日／來源／雙曲線、缺資料停用、31件不自動改量、1000件／輪次試算、原快照保留與刷新讀取。tests/browser_inventory.py既有6例一起重驗。
- tests/manual_replenishment.py：受guard限制，只在B自己的demo使用真實Edge登入b03manager，核對42／0／null、1000雨衣警示、讀回原值及全庫存／版本／時鐘不變；每次執行只新增一筆B03計算快照。本次已執行一次並PASS，截圖在Git忽略instance/browser-check。
- 對應V01–03、V12–14、V20、V22–24、V27、V29、V31、V39、V41、V49的B03部分；B04人工預測／歷史活動資訊／特殊直接模式、B05完整對帳／報廢退回未做。

本次實際檢查：

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_replenishment.py tests/browser_inventory.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/replenishment.js
git diff --check
~~~

最終全套：2 failed, 219 passed in 146.51s；221例中B03新增48例全部通過，兩個失敗均為下列未改動的共用測試。真實Edge回歸9 passed in 26.29s（B03 3＋B02 6，無skip）；持久化demo真實Edge核對PASS。環境兩行PASS，db check：No new upgrade operations detected，node --check與git diff --check結束碼0。

另於APP_ENV=demo、MODULE_DEV=B執行 inventory prepare-b03-demo（首次新增，重跑保留）及 tests/manual_replenishment.py（上述兩行PASS）。首次B03專用40例22.44s；補充案例後發現新CLI測試的交易Connection無url，已修正為取實際engine.url；47例27.38s通過後增加一例Decimal精度可重現性，由最終全套驗證。以最後結果為準，未將過程失敗掩蓋為全套通過。瀏覽器6例B02為回歸，3例B03為本階段，合計9例26.29s，無skip、無warnings summary；另一筆持久化demo真實Edge核對PASS。db check無新upgrade，node及diff退出碼0；Git只有既有LF→CRLF提示。

### 尚待A協調的共用測試

1. tests/test_contracts.py::test_no_silent_fallback：該測試未移除runs插槽，仍假設尚未實作而期待get_provider('runs')503。現在正式B已註冊runs，取得它是正確行為；真正缺D時，生成仍503，新增B測試已證明無靜默fallback。請A調整測試前置以測「缺插槽」本身，保留原合約語意。
2. tests/test_contracts.py::test_independent_module_boot[C-expected1]：app/routes/module_dev.py硬找controlled-test-v1／找不到時run_id0。合約要求正式提供者不被替身覆蓋，B03提供者不接受控制快照／非法id，故該開發頁422。請A協調共用開發頁與C獨立模式的provider／快照選擇；不可把受控快照假稱正式B結果。

這兩处A負責的檔案與凍結測試未修改，亦未用skip／xfail或測試fixture隱藏失敗。正式B生成／讀取／evaluate與C真實草稿的最小相容已通過；MODULE_DEV=C共用示範入口仍有上述限制。此階段不能宣稱整個儲存庫全綠或正式產品整合完成。

## 現在請B做什麼

停止舊Flask後，依[B03畫面核對指南](../b03-manual-testing.md)啟動APP_ENV=demo／MODULE_DEV=B，用b03manager開 http://127.0.0.1:5000/store/replenishment 。L1看飲料42／雨衣0／泡麵無有效建議；展開曲線確認先銷售後到貨；試31件看INVALID_PACK，L3看S90／建議84，雨衣1000看大量／容量；再讀原快照看42／0不變。驗收指引包含完整URL、角色、時間、來源、錯誤、手機、跨店及404判讀；不可只貼匿名HTTP_404 JSON替代身份／URL。

可貼聊天：

> 我是B，我已核對B03，版本5ca0263＋本機B03修改，快照〈編號〉；飲料／雨衣／泡麵〈數字〉，L3／1000試算〈警示〉，31件〈錯誤〉，原快照及庫存〈結果〉，手機／權限〈結果〉。請記錄，仍停在B03，不commit、不push、不開PR，不進B04。

先保留本機修改，無本次發布授權，不準備PR、不替B發布。完整模組Ready PR與真實跨模組整合依agent.md後續階段；B01「70 passed in 48.61s」維持原人工紀錄。

## B02 改動、測試及界線（前次歷史）

- app/services/sales.py：嚴格 UTF-8 CSV 整批逐列驗證；固定21:00區間；門市／商品／日期／件數／營業／缺貨檢查；簽章預覽綁定內容、提交者、門市版本，15分鐘真實時間期限。提交先查原成功批次，再驗新提交期限／版本；同來源不同內容409。
- 整批更正明確指定原批次與理由、換新來源識別；一次取代原批次所有有效列。歷史只更新預測；未被盤點涵蓋且尚未入帳才可轉日常；日常更正只追加銷售差額，不降回歷史。
- app/models/sales.py：原批次／提交快照封存後不可改寫或刪除；修正新增批次，保留每列前值與快照。使用既有表及欄位，沒有schema／migration變更。
- app/services/inventory.py：跨盤點更正建立 sales_covered 對帳紀錄、H暫不可用；有效盤點／合法修訂後解除。保留負帳面與原異動，庫存完整性不能用歷史檔繞過。
- app/modules/inventory/routes.py、app/templates/inventory/data.html、獨立 inventory.css／inventory.js：/store/data、CSV驗證／提交、庫存狀況、盤點／修訂，店長權限／跨店／CSRF與最外層交易。提交結果不明時保留本人本店原請求，重新整理仍可重試；任何有效變動後使舊預覽失效。
- app/modules/inventory/demo.py：B 自己本機 demo 的 additive prepare-demo 指令，不刪／重設／倒退／覆寫憑證。demo/sales_sample.csv 與本店本日下載入口提供明示合成資料。
- tests/test_sales.py：MySQL整批回滾、預覽只讀、來源唯一／原結果重試、模式切換／盤點涵蓋、差額／缺口／負值／對帳、權限／CSRF、非法原入帳來源、多日／整批範圍、真實時間token期限、兩連線同來源／不同來源競爭。
- tests/browser_inventory.py：真實Edge桌面1280px與手機390／320px、20px字體不橫向溢出；18→受控收貨28→盤點30→修訂31；錯誤CSV、修改預覽失效、回應遺失＋刷新恢復；歷史→日常、負帳面、跨盤點更正及解除。截圖只在忽略的instance/browser-check/。
- 鎖順序遵守門市→商品id升冪庫存→來源鍵；銷售／庫存／稽核／版本／對帳均在呼叫端同一session，只有路由／CLI transaction commit／rollback。失敗全批回滾。
- 凍結合約v1、spec、A／C／D檔案均不變。MODULE_DEV=B只對D未結來源使用指定替身；B02庫存及銷售沒有替身。B03計算、B05完整對帳／報廢／退回、真實C／D整合與完整V驗收尚未完成。
- 自測中修正了成功提示早於庫存刷新、瀏覽器測試受控輸入的舊版本、token期限測試誤影響CSRF及鎖順序整理時漏掉Inventory匯入；以最終程式重驗，結果以下列最終證據為準。

本次實際檢查指令（根目錄、先載入B本機環境）：

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_inventory.py -x -q -p no:cacheprovider
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/inventory.js
git diff --check
~~~

最終結果：全套173 passed in 155.69s；Edge 6 passed in 28.00s、沒有skip；環境兩行PASS；db check：No new upgrade operations detected；node語法檢查與git diff --check結束碼0。最終pytest／Edge沒有warnings summary；Git僅有LF→CRLF提示。Playwright 1.63.0只安裝本機.venv，不更改共用requirements。

[完整B02畫面核對指南](../b02-manual-testing.md)提供起點／登入／URL／檔案／批次ID／每步數字、錯誤、跨店、手機及回報方式；B人工結果尚未回報。對應V21、V32、V33、V46、V48、V49的B02模組證據，不等同產品整體通過。

## B01 改動與對外界線（前次紀錄）

- app/services/inventory.py：InventoryService.apply_movement(mutation=…, session=…) 與 get_integrity(store_id=…, product_id=…, baseline_at=…, session=…) 符合合約 v1；submit_count 為 B 自有服務入口，B02 才提供盤點路由／畫面。
- app/modules/inventory/services.py：只註冊正式庫存寫入與完整性提供者。
- app/models/inventory.py：ORM 守衛保護盤點原始帳面／身份及冪等來源；只允許主紀錄 version 正常遞增，沒有改表或 migration。
- tests/test_inventory.py：MySQL 同交易回滾、來源作用域／內容衝突、成功重試優先、差額與損壞量、負帳面、日期缺口、不可變記錄、兩連線盤點／來源競爭，以及既有讀取快照下的新版本重驗。
- tests/manual_inventory.py：可重複的後端數字核對，拒絕非空 test DB，不 commit，結束回滾且確認36張業務表仍空。
- docs/handoffs/B.md：本次交接。

有效異動沿共用 bump_store 更新門市計算版本，同時遞增 Inventory.version。所有查詢／寫入／稽核使用呼叫端 session，沒有內部 commit／rollback；最外層必須在失敗時回滾。寫入及 H 查詢均先取得門市鎖，再以 MySQL 目前資料刷新庫存、入帳來源、盤點及來源結果，避免 REPEATABLE READ 舊快照造成重複或錯誤差額。

盤點首差額從目前帳面逆推截止後異動取得21:00帳面；修訂只用「新實盤－前次有效實盤」。更換 key 不會建立第二主紀錄，合法修訂要 correction=True、理由、expected_count_version 及最新 Inventory expected_version。同鍵不同內容409；相同內容重試仍回當時結果，即使後來再收貨、修訂或已過22:00。

入帳完整性只承認正確區間的 daily_posting、applied_at 及本店本商品的有效銷售異動來源；歷史資料、空來源、錯誤來源或日期缺口不算入帳。負帳面保留原有號值及 OPEN 對帳紀錄，不歸零；收到更多貨也不靜默解除，須合法銷售更正或有效盤點。待對帳時有效盤點基準暫不可用，IntegrityDTO.baseline_counted_at／h 為 null，原 Inventory.counted_at 保留。B05 再提供完整對帳操作。

正式 B 異動以不可變 audit_events 保存 payload_hash 與原 MovementResult，不新增欄位。舊 ControlledInventoryWriter 產生而未具正式快照的來源不能冒充正式已入帳結果，會回 SOURCE_RESULT_UNAVAILABLE 409。使用替身的 demo／fixture 不應直接當正式整合資料。

## B01 前次實際自測

環境檢查先確認兩個隔離 DB 連線與 migration head，測試僅用 test DB。所有命令在專案根目錄執行，先載入本次本機專用環境：

~~~powershell
. .\instance\b01-test-env.ps1
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_inventory.py tests/test_contracts.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe tests/manual_inventory.py
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
git diff --check
~~~

結果：環境兩行 PASS；全套121 passed；最後 B01＋凍結合約70 passed；數字核對及回滾 PASS；db check 顯示 No new upgrade operations detected；git diff --check 無錯誤。pytest 無 warnings summary；Git 另有既有 autocrlf 的 LF→CRLF 提示，非測試警告。

## B01 前次核對方法（保留歷史，不是本次 B02 起點）

1. 在 C:\Users\USER\Desktop\system2 開 PowerShell；沒有 Flask 啟動需求。保留未提交修改，先執行：

~~~powershell
Set-Location C:\Users\USER\Desktop\system2
git status --short --branch
git rev-parse --short HEAD
git merge-base --is-ancestor a03-parallel-v2 HEAD
. .\instance\b01-test-env.ps1
.\.venv\Scripts\python.exe scripts/check_environment.py
~~~

預期：feat/b-module、HEAD=f2d5f67；祖先檢查結束碼0；只有上述6個B檔案修改／新增；兩行 PASS、head=884e7a53a8c8。instance/b01-test-env.ps1 只屬這份 checkout，包含本機憑證，不貼內容、不提交。其他 checkout 依 README 建立自己的 B demo／空 test DB 及 .env，不複製此資料目錄。

2. 執行純服務數字核對：

~~~powershell
.\.venv\Scripts\python.exe tests/manual_inventory.py
~~~

身份／資料：合成 manager1、DEMO1、首兩個商品，數量以件。腳本在 test 交易內建立示範資料，準備前一日21:00已核對盤點基準及當日 daily_posting 合成輸入；本輪截止點2026-10-08 21:00 Asia/Taipei，提交時間21:20。銷售列與 receipt mutation 為受控輸入；庫存、盤點、冪等及回滾均使用正式 B 服務，不使用 ControlledInventoryWriter，也不宣稱 B02 匯入或 D 收貨已完成。

| 核對項 | 預期 |
| --- | --- |
| 當日銷售測試輸入 | 21:00帳面18 |
| 21:10可售收貨10 | 目前帳面28 |
| 21:20提交21:00實盤20 | 差額+2、目前帳面30，保留後續收貨 |
| 同鍵同內容重送 | replayed，仍30 |
| 同鍵改為21 | IDEMPOTENCY_CONFLICT，HTTP409 |
| 換新鍵試圖重建同截止點 | COUNT_ALREADY_EXISTS，HTTP409 |
| 明確修訂實盤21 | 只加1至31；一主紀錄、兩不可變修訂，H=31 |
| 另一品項銷售25 | 帳面-5、OPEN對帳、H=null，不歸零 |
| 次日缺日常入帳 | 缺2026-10-09、H=null |
| 結束 | 回滾36張業務表測試資料，保留schema／migration；未commit |

3. 核對錯誤、損壞量與兩連線競爭：

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_inventory.py tests/test_contracts.py -q -p no:cacheprovider
~~~

預期70 passed。包含損壞只加實體／不可售而不增加H、失敗後全交易回滾、同來源兩次併發只入帳一次；不同來源但同舊 Inventory.version 只有一個成功，另一個409；同盤點鍵競爭只建一次主紀錄，修訂競爭只有一個成功。這些是 B 服務測試，不含真實 D receipt／C submission 的整合承諾。

測試 DB 非空時腳本拒絕，不要求 reset-demo／clean／drop tables；先回報原因。這份隔離 MySQL 已啟動於3308；若重開電腦後無法連線，只啟動既有資料目錄（不 initialize），再跑環境檢查：

~~~powershell
Start-Process -FilePath 'C:\Program Files\MySQL\MySQL Server 9.6\bin\mysqld.exe' -ArgumentList '--no-defaults','--basedir="C:/Program Files/MySQL/MySQL Server 9.6"','--datadir="C:/Users/USER/Desktop/system2/instance/b01-mysql-data"','--port=3308','--bind-address=127.0.0.1','--mysqlx=OFF','--log-error="C:/Users/USER/Desktop/system2/instance/b01-mysql.log"' -WindowStyle Hidden
~~~

只在3308未啟動時使用。不要使用A的3307啟動腳本、改寫.env或重建此資料目錄。
