# B 模組交接

## A 協調更新：2026-10-11

- B 的 [PR #3](https://github.com/KL-0728/system2/pull/3) 已由使用者合併；B head=952d99f，合併 main=527ba2e。下方「尚未提交／未建立 PR」屬當時歷史，不是目前 GitHub 狀態。
- A 修正共用測試前置、C 的來源選取、開發入口與舊草稿處理，詳 [提供者整合修正與實測](../provider-integration.md)。B 正式拒絕受控快照／無正式入帳來源的保護保留，沒有變更補貨公式或產品規格。
- 人類 B01–B05 實測結果仍待 B 自行補入；本次 A 自測不代填人類或完整產品驗收。
- B 已合併模組的後續補修依 agent.md 開新 fix 分支；不要再推送已合併的原模組分支。

## 2026-10-11 B05（目前狀態，以本節與下方B05列為準）

請B現在依 [B01–B05完整人工指南](../b05-manual-testing.md) 操作並回報；人類實測尚未回報。本次只做B05後停下，不commit／push／開PR／合併main。以下B01–B04章節是歷史紀錄，並非目前仍停B04。

- 開工已讀AGENTS.md、agent.md、spec.md、README.md及凍結docs/contracts.md v1。feat/b-module乾淨起始，git fetch origin --tags成功；git pull --ff-only回Already up to date。
- HEAD與origin/feat/b-module：f5867b6bcd30d681e17070f831b99b18ee2eb624；測試版本是此SHA加未提交B05修改。origin/main=f2d5f67452ac249fe14a979a1433d69fa2802236；a03-parallel-v2發布提交=1744fbd01446597b3be6c552b991476d86950b75（annotated tag物件25994e3842da222bf45514f7588b0ed9abd5e273）。兩項ancestor檢查exit0，基準未變。
- 保留既有B01–B04、所有門市與私有instance環境；未改spec、合約v1／凍結合約測試、A／C／D檔案、schema、migration、requirements或.env。
- 新增app/services/inventory_operations.py、operations_routes.py：店長有來源與expected_version的報廢／退回，實體及不可售同減、不加H、原收貨保留；成功原請求先冪等重放，變更內容409。Store→Inventory→來源鎖、同caller交易，沒有服務內commit。
- 對帳讀取及有效盤點處理：同時核對庫存／案件版本與request_key；negative_book差額15恢復H，sales_covered修訂差額0保留截止後收貨。處理結果保存actor、time、reason與盤點修訂id；未真的解除案件就整筆回滾。
- B的inventory.py／sales.py補存新對帳的manager責任、政策variance_hours期限、政策版本；有效處理仍保留這些欄位，逾期不自動結案。使用既有resolution JSON，未新增表。極小fixture無StoreProduct時使用明載來源的bootstrap-policy-v1預設；正常配置保存實際政策版本。
- B資料頁新增預覽／來源／唯讀異動與案件歷史、手機版、原請求重試與未知回應復原；送出／未知結果鎖定其他寫入，刷新仍可同鍵重試。最新100筆各自只讀查詢。
- prepare-b05-demo只新增自己的B05DEMO／b05manager合成案例。初次利用正式B日常、盤點、更正、庫存服務；收貨仍明示合成來源。既有B05僅缺期限時補存自有合成案件 metadata／version與audit，其他門市、庫存、銷售、密碼、業務時鐘保留。
- 新增正常／錯誤CSV、服務／真實MySQL併發／Edge測試、可回滾數字腳本、唯讀示範瀏覽器核對、完整指南及 [本機PR內文](B-pr.md)。
- 對應V32／V33／V46／V48／V49的B側來源、差額與阻擋，V45僅B損壞品報廢／退回部分；V45子案件額度／補送併發及正式D閉環由A整合，不能填整條V通過。

### 實際最終自測

Python3.12、MySQL9.6 InnoDB 127.0.0.1:3308，system2_b01_demo／system2_b01_test隔離，migration head=884e7a53a8c8；Playwright1.63與真實Edge。

在C:\Users\USER\Desktop\system2依序實際執行：

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_inventory_operations.py tests/browser_inventory.py tests/browser_replenishment.py tests/browser_forecast_modes.py -q -p no:cacheprovider
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
.\.venv\Scripts\python.exe -m flask --app wsgi inventory prepare-b05-demo
.\.venv\Scripts\python.exe tests/manual_inventory_operations.py
.\.venv\Scripts\python.exe tests/manual_inventory_operations_browser.py
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/inventory.js
node --check app/static/js/inventory_operations.js
git diff --check
~~~

- 環境兩行PASS；完整pytest：**2 failed, 303 passed in208.66s（305例）**，涵蓋B01–B05與凍結合約。新增B05服務31例均在此套通過，含真實兩連線MySQL來源競爭、交易回滾、CSRF、角色／門市拒絕、期限逾期仍OPEN。
- 正式Edge最終：**17 passed in57.63s**（B05五例、B02六例、B03三例、B04三例），1280／390／320px及20px字體、報廢／退回／盤點對帳、原請求與回應遺失刷新復原、模型／人工／直接訂購；無skip或warnings summary。
- manual_inventory_operations.py五行PASS：32/2/H30→30/0/H30、原收貨保留／同鍵只扣一次；雨衣-5→count10差額15、泡麵count20差額0保留book30；正式B模型Q24/42/15/null、manual5.125→Q13、direct1000容量1008/null無曲線；錯誤CSV整批拒絕、歷史補日不扣H8與重試／補全後Q42。最後所有服務寫入回滾，比對全部36表筆數、門市／庫存／銷售版本與時鐘不變。
- manual_inventory_operations_browser.py兩行PASS：真實Edge以b05manager登入B05DEMO(id6)，初始32/2/H30、-5/Hnull、30/Hnull、8/H8；兩筆OPEN政策期限、他店404；手機資料／補貨畫面無JS error／水平溢出；所有表筆數／版本／時鐘保留。
- db check：No new upgrade operations detected；兩支node --check exit0。git diff --check見最終差異核對（exit0；Git可能提示LF→CRLF，不是測試warnings）。
- 截圖僅在Git忽略instance/browser-check：b05-operations-1280/390/320.png、b05-demo-start-390.png。不包含憑證。

### 已知共用失敗與整合界線

1. tests/test_contracts.py::test_no_silent_fallback假定runs未註冊；正式B已註冊runs，未拋原預期503。A需使未註冊測試情境明確，不能移除正式B服務或造fallback。
2. tests/test_contracts.py::test_independent_module_boot[C-expected1]：A共用module_dev硬選controlled-test-v1/run_id0；正式B拒絕非自身有效快照，回422而非期待200。A需協調C開發入口與正式／受控provider使用。

兩項自B03即已記錄，B04完整回歸仍失敗；本次未改凍結測試、未skip／xfail，沒有宣稱全套全綠。MODULE_DEV=B的D open_orders依然ControlledOpenOrders；正式B→C的隔離模組案例使用真實B與C，但D輸入受控。正式D接單／分批收貨／額度／未結量、A管理與全V人類驗收留A05／A06。

### 組員現在操作與下一步

依完整指南先確認身份與初始數量，再做報廢1／重試、退回越界3／合法1、兩筆盤點對帳、L1建議24/42/15、人工5.125→13、直接1000→1008、歷史CSV差額0、手機與門市拒絕。資料寫入保存在自己的B05DEMO，prepare-b05-demo不會重設。詳細正常／錯誤預期、來源追溯與可填回報均已列在指南。

**人工實測：待B回報；PR：尚未建立，內文狀態Draft。** 本次不發布。可複製下一句：

> 我是B，已依B01–B05指南實測f5867b6＋本機B05。報廢／退回／原請求重試【結果】、兩筆對帳【結果】、模型／人工／直接【結果】、CSV與手機／權限【結果】；失敗步驟與錯誤【內容】。請記錄，先不提交推送。

人工確認及A協調後，再明確授權提交／推送／開Draft PR；不要現在標Ready或自行合併main。PR內文含可複製命令與審查範圍。本次在B05結束後等待指示。

---


## 2026-10-11 B04（本次，停在 B04）

- 已讀 AGENTS.md、agent.md、spec.md、README.md 及凍結 docs/contracts.md。開工 feat/b-module 乾淨；git fetch origin --tags 成功；git pull --ff-only 首次網路重設失敗、重試成功（Already up to date）。
- HEAD／個人上游 b1b06377775f6f8abf39302792b54f4209726e00；origin/main f2d5f67452ac249fe14a979a1433d69fa2802236 及 a03-parallel-v2 1744fbd01446597b3be6c552b991476d86950b75 均已在本分支歷史，祖先檢查退出碼0。被測版本為此 HEAD 加本機未提交 B04 修改。
- 只做 B04。不 commit、不 push、不開 PR、不合併 main、不 reset、不 clean；保留既有 B01 更正、B02、B03。未修改 spec、凍結合約 v1／消費端測試或 A／C／D 檔案，未覆寫 .env（此 checkout 沒有 .env）。B05 未開始。
- 環境沿用忽略的 instance/b01-test-env.ps1、Python3.12、MySQL9.6 InnoDB 127.0.0.1:3308；B 自己的 system2_b01_demo／system2_b01_test，migration head 884e7a53a8c8，未增加 schema／migration。
- B 正式 inventory_writer／integrity／runs 沿用同一 caller session；人工／註記服務不 commit 或 rollback，由呼叫端管理交易。Store 鎖及計算版本阻止舊資料覆寫；保存人工新修訂／歷史註記會提高 Store.calculation_version，不改庫存；生成／試算不提高該版本、不送訂單。
- 開發 D open_orders 仍為 ControlledOpenOrders。新增真實 B→C 測試在隔離 test DB 使用正式 C 草稿、預覽、重要確認及送單，僅 D 未結來源受控；這是有限相容證據，正式 D 閉環整合仍待 A05，產品 V 全套仍待 A06。畫面人工驗收由 B 回報後再記錄。

### 改動

- app/services/manual_forecasting.py：Decimal 字串／Decimal 非負有限、最多三位小數、上限1000000；帶入最近值／理由／actor／時間／期限。人工值新增修訂而非覆寫，依當時 PolicyVersion.parameters.manual_valid_days（預設7）設定第七日21:00期限，audit 留政策 id／版本。最新過期值只作參考、不退回更舊值。
- app/models/replenishment.py：僅增加 ManualForecastOverride 的更新／刪除不可變守衛，未改欄位、DDL 或共用不可變模型。修訂來源可追蹤，舊 run 保留當時人工值。
- app/services/replenishment.py：生成明選 model／manual／direct；人工每輪 product_id 明確確認，重新試算未確認時 FORECAST_INSUFFICIENT 阻擋，期限到點失效。manual 使用同一精確 Fraction／Decimal 整箱公式與時序；超量 null＋阻擋，不截斷。七日品質事實仍在 input_snapshot。
- direct 保存日期、說明用需求量、理由、安排及獨立候選訂量；mu、S、raw、suggested 均 null，無精確曲線。output_snapshot／DIRECT_ORDER.details 保存不扣任何銷售的保守現貨＋候選＋來源上界，含期外／逾期／爭議可能到貨；明示無法評估需求缺口。1000需求＋1000最終不會變2000。箱入、上限、截止、版本、庫存缺口／負帳面及物流檢查保留。
- 歷史銷售註記只改既有 SalesDaily.event_note／version、Store 計算版本及 audit，不補缺檔、不改 sold_qty／庫存。HISTORICAL_EVENT 是 info，歷史銷售仍納平均，不單獨產生 SPECIAL_DEMAND；本次直接需求另存於 run input_snapshot 並產生 important。
- B 自有路由加入 POST /api/replenishment/manual-forecasts、POST /api/sales/events，context 增加每商品最新人工參考／七日既有列，既有生成與試算支援模式選擇及確認。既有 v1 RunDTO／RunProvider 簽章不變；生成 API 新參數可選，B03 舊客戶相容。
- app/static/js/forecast_modes.js、replenishment.js、B 模板／CSS：分開人工日需求與直接候選訂量；人工未勾選拒絕、每次生成／讀取／試算重新確認；修改最終量或輪次取消試算勾選；顯示 actor、時間、期限及直接保守容量，模式各自呈現正確公式。重新核對版本／保存註記／生成後仍保留直接需求日期、數量、理由及安排，不保留人工勾選。
- app/modules/inventory/forecast_modes_demo.py、B routes.py：guarded additive prepare-b04-demo，僅 B 自己 demo DB／MODULE_DEV=B，已存在時原封保留，拒絕覆寫帳號，不重設時鐘／既有活動。新增 B04DEMO（id5）／b04manager、SKU01–04 的合成歷史／已核對初始庫存／政策與配送輪次，並一筆過期人工參考。
- tests/test_forecast_modes.py：B04 51 例，含精度／期限／最新過期不回退／每輪確認／快照不可變／回滾／CSRF／權限／版本／非法模式／庫存阻擋／null與保守容量／歷史資訊／真實 B→C 消費。
- tests/browser_forecast_modes.py：真實 Edge 1280／390／320，三位小數拒絕、人工 Q13、勾選失效、歷史 info、直接1000、試算1200、原值保存、20px無頁面橫向溢出、無 JS error。tests/manual_forecast_modes.py 在 B demo 做持久化真實 Edge 核對。
- 對應 B04 的 V12、V38、V41、V42、V49 部分；未將 B 模組測試當成所有產品驗收。

### 實際命令與結果

在 C:\Users\USER\Desktop\system2 執行（不需重新建庫）：

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/test_forecast_modes.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_forecast_modes.py tests/browser_replenishment.py tests/browser_inventory.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/forecast_modes.js
node --check app/static/js/replenishment.js
git diff --check
~~~

- 環境 demo／test 前後均 PASS、head 884e7a53a8c8。
- B03 專項 48 passed in 28.23s；B04 專項最後46 passed in31.68s（含真實 B→C 兩個案例）；其後新增5個期限／政策／精度／demo防護案例，完整回歸已全部通過，B04最終共51例。
- 全套 pytest：2 failed, 272 passed in182.89s（274例），沒有warnings summary。兩項失敗仍是原有 tests/test_contracts.py::test_independent_module_boot[C-expected1] 及 ::test_no_silent_fallback。凍結消費端的模式／DTO／業務案例通過，但不能說整份凍結測試全綠；兩項共用啟動假設請A協調。
- 最終真實 Edge：12 passed in40.06s（B04 3＋B03 3＋B02 6）；較早單獨 B04 3 passed in12.50s、B03 3 passed in11.00s，最後以合併12例結果為準，無skip、無warnings summary。
- 最後只改 B04 前端直接需求輸入保留，實際追加執行 pytest tests/browser_forecast_modes.py tests/browser_replenishment.py -q -p no:cacheprovider：6 passed in23.52s；最後 node --check 與 diff 檢查均0，沒有修改後端或重跑無關測試。
- db check：No new upgrade operations detected；兩支 node --check 和 git diff --check 退出碼0。Git只有既有 LF→CRLF 提示，無差異空白錯誤。

另在 APP_ENV=demo、MODULE_DEV=B 實際執行 inventory prepare-b04-demo 及 tests/manual_forecast_modes.py；最後 PASS，已保存人工 run#4（5.125/Q13）及直接 run#5（1000、null、保守1020）。所有庫存數量／版本、時鐘及其他門市版本未變；B04 自己只新增人工修訂、計算版本／audit 及 run。
過程 CLI 首次漏匯入模型而整筆回滾；示範核對先後修正既有 NEGATIVE_BOOK 代碼與快照選單 selector，先前已保存的 B04 人工修訂／run#2、#3保留，沒有 reset。人工相容測試曾因錯讀 C 回應欄位失敗，已修正 B 自有測試，C 檔案未變；以最後測試結果為準。
既有 favicon.ico 404 不影響登入或功能；/store/replenishment 應200。未隱藏／跳過兩項共用舊前提失敗，詳後方原有「尚待A協調的共用測試」。

### B 現在照做的畫面驗收

現在請 B 核對工作區及畫面；保留現有資料，不重新 seed／reset。若有舊 Flask，先在其終端 Ctrl+C，另於專案根目錄開 PowerShell：

~~~powershell
. .\instance\b01-test-env.ps1
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi inventory prepare-b04-demo
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
~~~

prepare-b04-demo 現在應顯示已存在／保留資料。不要再執行清庫命令，也不需建立 .env。瀏覽 http://127.0.0.1:5000/login，登入 b04manager；密碼沿用本機 DEMO_PASSWORD，可在另一個載入私有腳本的本機終端用 $env:DEMO_PASSWORD 查看，勿貼聊天或加入Git。帳號已用真實 Edge 登入成功。
同一瀏覽器開 http://127.0.0.1:5000/api/auth/me，核對 username=b04manager、stores 內 B04DEMO 的 id5（不是 user id）；接著開 http://127.0.0.1:5000/store/replenishment?store_id=5。若主頁顯示 C 工作台，不以其入口代替本次網址；MODULE_DEV=B 未設定或使用舊程序時，先按上述命令重啟，非預期 API404不要重設DB。

1. 確認業務時間2026-10-09 21:20（Asia/Taipei）、B=21:00、截止22:00；配送選第一輪2026-10-10 21:00、L1。未結來源會明示受控測試。展開「計算模式／人工值／歷史註記」。預設各商品七日模型；產生快照，飲料H20／μ20／S50／Q30，HISTORICAL_EVENT info，沒有因歷史活動新增SPECIAL_DEMAND。雨衣、泡麵缺一日顯示null／無有效建議；衛生紙待對帳，H不可用及NEGATIVE_BOOK。生成／試算不改庫存、不建立訂單。
2. 泡麵選「人工預測日需求」；最近有效值5.125、理由、設定者、設定時間及有效至2026-10-16 21:00應可見（最初過期參考仍保留於DB，最新有效值由AI自測保存）。填5.1251、理由後按「保存新人工預測」→拒絕最多三位小數，不產生修訂；改5.125及「已核對每日需求5.125件與活動交付安排」→保存成功、版本更新、checkbox仍未勾。
3. 不勾確認直接「產生並保存計算快照」→MANUAL_CONFIRMATION_REQUIRED；勾「我已核對本輪人工值、理由與期限」後生成→泡麵μ5.125、S20.25、原始12.25、向上整箱13件，MANUAL_FORECAST important；缺檔品質事實仍保留。記下快照id。
4. 原結果下方「本次試算已核對人工值與期限」預設未勾；直接試算→FORECAST_INSUFFICIENT block。勾選再試算→解除此未確認阻擋，每次顯示新的試算後勾選再次清空。改最終量／輪次亦須重新核對，勾選不代表C正式送單確認。從下拉選同一id「讀取原快照」→回原5.125／13，保存內容未改。
5. 泡麵模式改回「七日模型」，雨衣選「特殊直接訂購」；填日期2026-10-10、活動需求1000件、理由「社區活動需要一千件雨衣，已核對件數」、安排「到貨後直接交付活動單位」、本次直接候選1000。生成→mu、S、raw、suggested顯示「無法計算」，最終1000；無精確需求曲線；H20＋候選1000＋未結0=1020，常規容量100。DIRECT_ORDER／SPECIAL_DEMAND／LARGE_QUANTITY／CAPACITY重要警示，明示無法評估需求缺口；不是2020，不縮成容量100。
6. 雨衣最終改1200後試算→保守1220、輸入維持1200；讀原快照→1000／1020。改0試算→INVALID_QUANTITY阻擋。飲料七日正常，不允許特殊直接模式；直接試算飲料31件仍INVALID_PACK，不自動取30／36。
7. 展開飲料「歷史銷售註記」，選一個既有日期、輸入「歷史活動僅供資訊，銷售照常納入平均」並保存→原銷量、庫存不變，資料版本提高；新生成飲料仍μ20／Q30及HISTORICAL_EVENT info。此後用舊快照試算→VERSION_CONFLICT；仍可讀回舊快照，不能無聲更新舊輸入。
8. 衛生紙選人工並保存5／理由，勾確認後生成，或填完整直接特殊需求生成→H仍不可用、模型量null及NEGATIVE_BOOK，不能靠確認解除。不要在本次使用B05未交付的對帳操作來清除此合成案例。手機390／320px與放大文字應可使用，無整頁橫向溢出。

期限到點與最新過期不回退已由可控業務時間的隔離 MySQL測試驗證；本機 demo 時鐘保持不變，若要手動推進到期限需另行安排相應輪次與盤點／銷售，不要求為本次驗收破壞既有錄影資料。C正式重要例外與送單的有限相容由test DB驗證，此B畫面的「試算」不會建訂單。

成功可貼：「我是B，已依B04指南核對人工5.125→13、未確認阻擋、雨衣直接1000／容量1020、歷史註記info及庫存阻擋；仍停在B04，不提交、不推送，等我指示。」
失敗回報步驟、username／store id、HEAD＋本機差異、實際／預期、錯誤文字／warnings summary；不要貼密碼。B04人工結果尚未由組員回報；完整模組PR在B05後依授權再處理。

---

## 2026-10-11 B01 更正（前次紀錄）

本次只處理 B01。feat/b-module 開工乾淨；fetch 與本分支 pull --ff-only 成功，HEAD／個人上游 2735faa，origin/main f2d5f67 已在本分支歷史中。B02／B03 已有先前提交，本次未改其程式；不 commit、不 push、不開 PR、不合併 main。

改動：app/services/inventory.py 對新異動的 occurred_at ≤ Inventory.counted_at（count_revision 除外）在門市與庫存鎖內回 COUNT_COVERED_MOVEMENT／409，無庫存、版本、來源或稽核寫入；同來源既有成功結果先依冪等規則回傳。前次盤點後、本次盤點前的正常日常銷售仍可入帳。負帳面同商品只保留最早一筆 negative_book OPEN 對帳案件；後續異動沿用，若舊資料已有重複 OPEN，將其餘結案並記錄合併目標。B02 的完整對帳待辦操作仍按既有分工處理。

tests/test_inventory.py 新增兩個 MySQL 案例：盤點後補登20:50或21:00收貨+10皆409且帳面20、版本／異動／稽核數不變；盤點前日常銷售與已成功來源重送仍有效。負帳面連續銷售與收貨只有一筆 OPEN，更正後零筆 OPEN。調整既有測試時鐘，使A03種子已盤點後的正常收貨發生於21:01。tests/manual_inventory.py 也加入兩種409及一筆OPEN的數字核對。

環境：本 checkout 無 .env；使用既有、Git忽略的 instance/b01-test-env.ps1 與 B 專用 MySQL 127.0.0.1:3308。未建立／重設 DB、未套新 migration。scripts/check_environment.py 前後 demo／test 均 PASS，head 884e7a53a8c8。測試使用合成 manager1／DEMO1、2026-10-08 21:00 Asia/Taipei 時鐘與正式 B 服務；沒有真實 D 收貨、B02 CSV 或瀏覽器人工驗收。

本次在專案根目錄實際執行：

~~~powershell
. .\instance\b01-test-env.ps1
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest tests/test_inventory.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe tests/manual_inventory.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
git diff --check
~~~

結果：B01 MySQL 44 passed in 26.64s；manual_inventory.py 的正常、409、單一OPEN及36張表回滾檢查全PASS；diff檢查PASS。全套為 221 passed、2 failed in 231.54s，沒有 warnings summary；不宣稱全套通過。兩項失敗是 tests/test_contracts.py::test_independent_module_boot[C-expected1]（共用C開發頁422，舊測試期待200）與 tests/test_contracts.py::test_no_silent_fallback（正式runs已註冊，舊測試仍期待缺服務錯誤），均為前次B03已記錄的共用測試前提。本次不改A／C／D或凍結測試。

現在請B核對本次四個檔案的差異；需要自行重跑時，先在同一隔離B test DB載入私有腳本，再執行上述命令。預期 B01 44 passed、manual PASS；全套仍有上述兩個共用失敗，直到A協調修正。失敗請回報命令、HEAD、git status、實際／預期差異、錯誤訊息及warnings summary，勿貼憑證。可貼聊天下一句：「我是B，已核對B01更正，請停在B01等我指示。」

## Earlier B03 handoff (historical)

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
| B04 | 人工預測追加修訂／期限／每輪確認、歷史註記info、特殊直接null與保守容量、庫存阻擋及B畫面 | b1b0637＋未提交B04；新增51例於全套通過；全套272 passed／2既有共用失敗；Edge12 passed in40.06s＋受影響6例重驗23.52s；demo PASS | 待B依本次B04指南實測 | 已由組員提交f5867b6；本次沿同分支完成B05；共用假設待A |
| B05 | 損壞品同步移出／來源重試、有效盤點對帳、責任與政策期限、手機、種子數字與完整指南／PR內文 | f5867b6＋未提交B05；全套303 passed／2既有共用失敗208.66s；新增31例通過；Edge17 passed57.63s；demo數字5PASS＋唯讀Edge2PASS | 待B依B01–B05完整指南實測，未自動填通過 | B05本機完成；未提交／推送／開PR；Draft內文，共用失敗待A；停下等指示 |

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
