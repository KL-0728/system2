# B 模組交接

不清楚下一步時先看[組員操作入口](../team-start.md)。本次只授權 B02，沿用 B01 成果；完成後停止，不自動進入 B03–B05。畫面操作見 [B02 核對指南](../b02-manual-testing.md)。

- 任務：B02 銷售匯入與盤點操作已完成製作與 AI 自測；B01 組員回報結果保留。等待 B 畫面核對，停在 B02，不進 B03。
- 遠端：origin = https://github.com/KL-0728/system2；本次 fetch／pull --ff-only 成功。
- 分支：feat/b-module，已有 origin/feat/b-module 上游；本次 fetch origin --tags 與 pull --ff-only 成功，Already up to date，開工時工作目錄乾淨。
- 基準：origin/main f2d5f67452ac249fe14a979a1433d69fa2802236；HEAD／個人上游 a139a7a563d896448b10972b57d3f2bc49552220（B01完成）。main 已在本分支歷史中；a03-parallel-v2 1744fbd01446597b3be6c552b991476d86950b75 亦已驗為祖先。
- 合約：docs/contracts.md／app/contracts.py v1 不變；schema／migration head 884e7a53a8c8 不變。
- 本次被測版本：HEAD a139a7a **加未提交的 B02 修改**。下方 B01 自測為前次 f2d5f67＋當時本機 B01 修改的歷史證據，不混用兩次測試結果。
- 正式提供者：inventory_writer／integrity，由 app/modules/inventory/services.py.install() 註冊；不新增 runs，也不實作 C／D 流程。已註冊真實提供者不會被 MODULE_DEV 的替身覆蓋。
- 環境：Windows／Python 3.12／MySQL 9.6 InnoDB；本次建立隔離 127.0.0.1:3308、system2_b01_demo／system2_b01_test、.venv。B01 階段 demo 僅套 migration；B02 本次用 inventory prepare-demo 首次建立持久化合成帳號 manager1／manager2／operator／admin，密碼沿用本機 DEMO_PASSWORD；業務時間2026-10-09 21:20，demo尚未做B02匯入／盤點操作。既有 3306、.env、他人資料均未修改。資料及隨機本機憑證只存 Git 忽略的 instance/。
- B 核對回報：2026-10-11，B 回報「70 passed in 48.61s」，記為組員重跑測試通過；未另提供命令、版本及完整輸出。數字核對腳本、瀏覽器／手機與真實跨模組實測結果尚未回報。
- 提交／推送／PR／合併：B01 既有 a139a7a 已在個人上游；本次 B02 AI 均未執行，main 未新增提交。依本次指示停在 B02。
- 真實跨模組整合：待 A05；完整 V 驗收待 A06。以下是 V32／V33／V46／V48／V49 的 B01 服務部分證據，不等同 CSV、訂購、收貨及產品驗收完成。

| 階段 | 本次改動 | AI測試指令／結果／SHA | 人工步驟與結果 | 未完成／下一步 |
| --- | --- | --- | --- | --- |
| B01 | 同交易庫存異動、來源唯一與原結果重試；21:00盤點差額、不可變修訂與主紀錄基準、提交鍵冪等；H、連續日常入帳、負帳面對帳阻擋；正式注入 | 全套 pytest 121 passed；B01＋合約重驗 70 passed（B01 42、合約28）；數字核對 PASS；db check 無新增upgrade；f2d5f67＋未提交修改，命令詳見下文 | 2026-10-11 B 回報：70 passed in 48.61s；組員重跑測試通過，數字腳本／瀏覽器結果未回報 | 前階段結果已記錄；成果已由組員提交於a139a7a，本次沿用 |
| B02 | CSV整批驗證／提交／更正；歷史轉日常防重扣；盤點／修訂畫面；完整性／負帳面／跨盤點對帳阻擋；手機與原請求恢復 | 全套173 passed in 155.69s（B02服務／API52例）；真實Edge 6 passed in 28.00s；db check無新upgrade、環境PASS、node語法及diff檢查通過；a139a7a＋未提交修改 | 待B按B02畫面指南實測，不代填人工通過 | 完成後停在B02；不進B03，不提交／推送／開PR |
| 03 | 未開始 | 未執行 | 未執行 | 本分支02自測後才可開始 |
| 04 | 未開始 | 未執行 | 未執行 | 本分支03自測後才可開始 |
| 05 | 未開始 | 未執行 | 未執行 | 完整人工指南及模組PR交接 |

## B02 改動、測試及界線

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

## 現在該做什麼

請 B 依 [B02畫面核對指南](../b02-manual-testing.md) 從 http://127.0.0.1:5000/store/data 實測，回報實際步驟、批次ID、飲料／雨衣前後帳面及H、錯誤文字、a139a7a＋本機未提交修改。AI完成B02後停止；不將自動測試當成組員人工或產品驗收通過。

可貼到聊天：

> 我是B，我已依B02畫面指南操作，結果為〈步驟、批次ID、飲料／雨衣數字及H／錯誤文字〉。請記錄，仍停在B02，不commit、不push、不開PR，不進B03。

未來若要繼續B03，另明確指示；本次不準備發布。B01回報「70 passed in 48.61s」維持原紀錄，不擴大解讀為前次數字腳本／瀏覽器或完整人工驗收通過。
