# [B01–B05] 資料、庫存與補貨模組

> A於2026-10-11核對：此內文保留原交付歷史；實際 [PR #3](https://github.com/KL-0728/system2/pull/3) 已合併至 main 527ba2e，B head=952d99f。以下未建立PR／未提交狀態不再適用。共用失敗的 A 修正與最新測試證據見 [提供者整合紀錄](../provider-integration.md)；B 人類實測仍須由 B 補入。

## 成員、範圍與版本

- 成員：B；任務B01–B05。
- 分支／base：feat/b-module → main。
- A03發布基準：a03-parallel-v2發布提交1744fbd01446597b3be6c552b991476d86950b75；已同步origin/main=f2d5f67452ac249fe14a979a1433d69fa2802236。
- 對外合約：docs/contracts.md v1保持相容；spec與凍結合約測試未改。
- 模組狀態：**Draft內文，尚未建立PR、提交或推送本次B05**；人類實測待填，兩項共用合約假設待A。
- 對應驗收：V01–03／V12–14／V20–24／V27–29／V31–33／V38–42／V46／V48–49的B側證據；V45僅B損壞品同步減量部分，不宣稱產品全部V通過。

## 這次完成什麼

店長可維護銷售、21:00盤點與修訂、損壞品移出與對帳；日常只入帳一次，盤點差額保留截止後收貨，負帳面或來源缺口保持阻擋。正式B同交易庫存／完整性服務及不可變補貨快照供C／D接入；人工與特殊直接模式有明確來源及不能繞過的庫存檢查。

| 階段 | 完成內容 | 自測證據 |
| --- | --- | --- |
| B01 | inventory_writer／integrity同session、來源唯一、不可變盤點差額修訂、H與入帳缺口 | 本次全套重驗；B曾回報70 passed in48.61s |
| B02 | 整批CSV驗證／提交／修正、日常／歷史、CSRF與身份、同請求復原及資料頁 | 本次完整回歸及6例Edge |
| B03 | 正式runs、七日來源、精確進位／箱入／L風險、輸入與輸出快照、版本試算 | 本次完整回歸及3例Edge |
| B04 | 人工追加修訂／政策期限／每輪確認、歷史info、direct null／容量／特殊需求 | 本次完整回歸及3例Edge，包含正式B→C隔離案例（D受控） |
| B05 | 有來源損壞品報廢／退回、有效盤點對帳、責任／期限／結果、手機、種子／數字／人工指南 | 31個新增服務案例於全套通過、5例Edge、demo數字與唯讀畫面PASS |

## 資料及介面影響

- 對外InventoryWriter／IntegrityProvider／RunProvider v1不變；B API增加報廢／退回與案件處理／唯讀來源入口。維持caller session與由路由掌握交易提交。
- 未新增schema／migration／依賴；對帳既有resolution JSON增加責任／政策期限／結果，正常處理保留期限。既有不可變count／movement／manual／run保護持續。
- B05種子只在APP_ENV=demo、MODULE_DEV=B、system2_b*_demo下新增B05DEMO／b05manager；已存在時不重建庫存／銷售／密碼／時鐘。自身合成案件缺期限可補metadata／version及audit。
- 本機環境變數名稱：DATABASE_URL、TEST_DATABASE_URL、SECRET_KEY、DEMO_PASSWORD、APP_ENV、MODULE_DEV；沒有提交.env、憑證、DB或截圖。
- 無spec／合約v1／A／C／D改動，沒有破壞性操作。
- [B交接](B.md)、[完整人工驗收](../b05-manual-testing.md)。

## AI實際測試結果

被測版本：f5867b6bcd30d681e17070f831b99b18ee2eb624加未提交B05修改（授權提交後需更新head）。Python3.12／MySQL9.6 InnoDB 3308，system2_b01_demo與system2_b01_test，migration884e7a53a8c8。

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_inventory_operations.py tests/browser_inventory.py tests/browser_replenishment.py tests/browser_forecast_modes.py -q -p no:cacheprovider
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
.\.venv\Scripts\python.exe tests/manual_inventory_operations.py
.\.venv\Scripts\python.exe tests/manual_inventory_operations_browser.py
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/inventory.js
node --check app/static/js/inventory_operations.js
git diff --check
~~~

- 環境demo／test PASS；全套 **303 passed、2 failed in208.66s**，包含B模組及凍結合約，未skip／xfail。B05新增31例均通過。
- 真實Edge **17 passed in57.63s**，1280／390／320及20px字體，含兩類失回應刷新同請求復原。
- demo數字5行PASS、唯讀Edge2行PASS；數字服務寫入全回滾，全部36表筆數、庫存／門市／銷售版本及時鐘保持。初始b05manager/B05DEMO門市id6已核對，權限他店404。
- db check沒有新upgrade；JS語法／diff檢查exit0。測試無warnings summary；Git的LF→CRLF提示另列為行尾設定提示。
- 兩項已知共用失敗：test_no_silent_fallback假定正式B未註冊runs；test_independent_module_boot[C-expected1]的共用入口硬選controlled-test-v1/run_id0，正式B回422。自B03／B04已有，A需協調入口／測試情境；不能改凍結合約來遮蔽。
- MODULE_DEV=B的D open_orders為ControlledOpenOrders。正式B→C隔離測試可證B／C契約使用，但沒有真實D履約的證據。

## 組員實測方式與結果

- 詳細身份、啟動、正常／錯誤／重試及數量見完整人工指南。
- 身份：b05manager，B05DEMO id6；密碼取本機DEMO_PASSWORD，未在文件輸出。
- 業務時間：2026-10-09 21:20 Asia/Taipei；截止點21:00。
- 人工實測者／日期／版本：**待B填寫**。
- 結果：**尚未回報，保持Draft**。

| 操作 | 預期結果 | 人工實際結果 |
| --- | --- | --- |
| 報廢1／重試、退回越界3／合法1 | 32/2→31/1→30/0、H30不變；越界拒絕、原來源保留 | 待填 |
| 雨衣count10；泡麵count20修訂 | -5差額15→H10；修訂差額0仍book30；案件結果／期限可追溯 | 待填 |
| 模型L1、人工5.125、直接1000 | 24/42/15/null；人工13；direct容量1008且無模型曲線 | 待填 |
| CSV錯誤／歷史／重試 | 整批拒絕；差額0/H8；補全模型Q42；原請求不重入帳 | 待填 |
| 手機／門市 | 390/320px與20px字體可讀、自己成功／他店404 | 待填 |

## 待A集中整合驗證

- 真實D批次／來源、接單／出貨／分批收貨、不可售移出與子案件失敗額度、未結量U／C扣抵；V45補送與差異併發。
- 真實C草稿→總覽→確認→送單、時鐘／狀態變更後重預覽，以及D到貨後B庫存同交易和冪等。
- A管理、政策、示範重設、登入權限、全V與至少三位測試者易用性；本模組自測不能代替A05／A06。
- 協調上列共用入口與凍結合約測試假設。沒有本次migration需要合併。

## 交付核對

- [x] feat/b-module，main為預定base，A03基準相容
- [x] 只改B檔案；沒有.env／憑證／DB／截圖
- [x] 模組與合約測試執行，失敗／替身明列
- [ ] 人工實測結果由B填入
- [ ] A協調共用失敗與是否可Ready
- [x] 人工指南及個人交接已備妥；本機PR內文Draft，不自行合併

## 之後取得授權才執行（本次未執行）

先核對只選B檔案，提交後更新本文被測SHA與人工結果，再依授權push／Draft PR。不得直接git add .將私有檔案混入。

~~~powershell
git add -- app/services/inventory.py app/services/sales.py app/services/inventory_operations.py app/modules/inventory/routes.py app/modules/inventory/operations_routes.py app/modules/inventory/operations_demo.py app/static/css/inventory.css app/static/js/inventory.js app/static/js/inventory_operations.js app/templates/inventory/data.html tests/test_inventory_operations.py tests/browser_inventory_operations.py tests/manual_inventory_operations.py tests/manual_inventory_operations_browser.py demo/b05_historical_sample.csv demo/b05_invalid_sample.csv docs/b05-manual-testing.md docs/handoffs/B.md docs/handoffs/B-pr.md
git diff --cached --check
git diff --cached --stat
git commit -m "feat(B05): 完成損壞品移出、對帳及B模組交付"
git push origin feat/b-module
gh pr create --draft --base main --head feat/b-module --title "[B01–B05] 資料、庫存與補貨模組" --body-file docs/handoffs/B-pr.md
~~~

未授權時保持所有修改在本機，不執行上面命令。本次沒有建立PR，沒有PR網址。人工結果和A協調完成後，再依agent.md由B／A決定Ready，等待A集中審查與整合。
