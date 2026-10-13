# A 整體優化與收尾證據

本文件保留前一輪未提交工作的歷史證據。2026-10-13使用者已以A身分授權全部既有修改納入、全系統檢查及直接推main；最新檢查、發布驗證及限制以[本次檢查報告](project-review-2026-10-13.md)為準。下方「未提交／等待授權」描述當時狀態，不作目前發布前置要求。

2026-10-13；身份A；分支 `chore/a-project-completion`；同步基準 `origin/main = HEAD起點 = b45cccb`。起始工作目錄乾淨，已fetch並pull --ff-only；main含D PR #6，D head `dd39baf`。以下測試使用本次未提交修改，不宣稱main已包含A收尾成果。

## 改動

- 新增 `/admin` 商品／門市／帳號／門市商品政策管理，後端限admin、CSRF、驗證、版本衝突及交易回滾；帳號停用立即在下一次請求撤銷登入，禁止管理者停用自己。密碼不出現在API／稽核。
- 政策追加 `PolicyVersion`，商品箱入數變動同步建立各門市新政策；遞增受影響門市計算版本，使舊預覽失效。新計算允許本輪B之後已生效的政策，符合spec政策／收貨更新須重新預覽；歷史快照保留。
- 新門市商品只建立標示未核對的空帳，不假造有效盤點。管理者可準備當輪配送；重按不重複輪次。每日基準21:00、截止22:00維持本版既有規則，未新增任意時刻盤點功能。
- 示範時鐘管理、向前／暫停控制及真實／業務時間稽核；正式環境拒絕修改。安全重設沿用既有本機CLI身份及固定字串，沒有新增未驗證的網頁重設路徑。
- 首頁／日常選單接入收貨、供貨待辦及截止提示；operator入口接入履約，admin有管理入口。收貨頁保留門市選單，URL指定門市會被後端授權並由前端選取。
- 庫存完整性新增選用批次方法 `get_integrities`，當輪有效盤點商品批次讀取，較早／較晚盤點仍走原完整異動驗證；五種狀態與原單品查詢逐一比對。D未結來源批次取得出貨、補送及配送資料，十個未結品項來源查詢不超過六次。
- MySQL REPEATABLE READ下，取得門市鎖後改用最新鎖定讀取收貨／出貨／補送／差異資料；未結来源亦讀最新資料，避免舊快照使同鍵重送失敗或允許不同鍵超量。保留原請求冪等、不可變原訂量、收貨與庫存同交易。
- 履約HTTP寫入補上spec要求的expected_version；新操作須使用畫面當時訂單版本，缺版本422、舊版本409。成功冪等請求仍優先核對payload並回原結果。內部D服務簽章不變，但直接HTTP呼叫者须增加此欄位，詳contracts更新說明。
- 履約與收貨改為商品名稱、中文狀態／待辦及台北時間，ETA輸入保留+08:00；時間軸預設摘要、可展開供貨前後值及收貨紀錄。
- 準備完整人工實測、PR文字、教學腳本及三人逐人計時表，未代填真人或影片結果。

跨模組變更涉及B的批次完整性、C預覽消費、D未結／併發讀取、履約HTTP版本前置條件及共用首頁。請B／C／D依PR檢查各自介面；沒有改唯讀DTO v1、依賴、已發布migration、spec或歷史提交。庫存新增方法是相容延伸，沒有該方法的受控提供者仍可使用原get_integrity；D HTTP消費端已隨本次前端與測試遷移。

## 環境與資料保留

Windows 11 build26300、Python3.12.6、MySQL9.6.0／InnoDB、A本機3307。CPU：Intel Core i7-13620H，16邏輯處理器；沒有取得記憶體大小，亦未測跨硬體／正式負載。

開始時3307拒絕連線，已使用既有 `scripts/start_a_mysql.ps1` 啟動，沒有初始化／重設DB。`check_environment.py` 確認demo／test各PASS、head `884e7a53a8c8`。自動測試在獨立test DB外層交易回滾；兩連線案例只對確認空的test DB建立並清理自己資料。demo只讀確認BCDEMO各20／0、時鐘21:00，未改demo或.env。

## AI實際驗證

| 驗證 | 指令／內容 | 結果 |
| --- | --- | --- |
| 合併後基準 | `python -m pytest -q`，b45cccb | 339 passed / 201.27s |
| 新管理功能 | `pytest tests/test_management.py -q`，第一版 | 修正雙test client共用應用context造成CSRF快取後，16 passed / 15.66s；新增門市案例待最終全套結果 |
| 真實閉環 | `pytest tests/test_full_integration.py -q -s` | 3 passed / 5.65s；正式B生成、C送單、D接單／出貨／收貨、B可售與不可售正確；無替身／fixture訂單 |
| 收貨原子回滾 | 真實B寫入後注入失敗 | 第一次履約與庫存都回滾，同key重試後只加一次；失敗注入不改正式提供者 |
| 兩連線收貨 | `pytest tests/test_fulfillment_concurrency.py tests/test_full_integration.py -q`，收貨修正版 | 5 passed / 9.26s；同key兩個200指向一筆receipt，不同key200／422，库存20→50一次。後加出貨及舊來源快照案例併入最終全套 |
| Edge管理／真實閉環 | `pytest tests/browser_a_completion.py -q`，第一版 | 5 passed / 28.43s；管理1280／390／320px、真實正常送單→接單→出貨→收貨1280／390px，無JS錯誤／橫向溢出；首次失敗是測試誤等導航及多個同名收貨按鈕，已修正腳本並重驗 |
| 效能 | `pytest tests/performance_integration.py -q -s` | 1000商品、14000歷史銷售、真實提供者，生成2.645s，1 passed / 8.15s；達本機五秒目標。十品項真實送單0.136–0.177s；不是1000品項提交或端到端網路壓測 |
| Node | `node --test tests/ordering_ui.test.cjs` | 2 passed；management.js／fulfillment.js語法檢查通過 |
| migration | `APP_ENV=test flask db check`、`flask db heads` | No new upgrade operations；單head 884e7a53a8c8；空test重建待最終紀錄 |
| 中途完整回歸 | `pytest -q`，中途版本 | 360 passed / 357.38s；新增案例與後續修改不援用此結果，須看下面最終紀錄 |

最終回歸與環境重建結果見下方補驗紀錄；不能以中途結果宣稱最終全部通過。

## 任務判定與最後待辦

| 任務 | 已完成的本機成果 | 尚需的真實行動 |
| --- | --- | --- |
| A04 | 管理設定、政策稽核、時鐘及共用入口 | 成員複核管理操作與設定影響 |
| A05 | 真實B/C/D閉環、回滾、未結來源及兩連線驗證 | A修改尚未提交／合併main；審核後依授權合併並重驗實際main SHA |
| A06 | 自動化回歸、桌面／手機、效能、空test遷移驗證 | V01–V50逐項完整產品證據、三位真人各兩分鐘／無口頭協助；沒有以模組替身測試代填 |
| A07 | 真實流程腳本、錄影案例、PR及交付指引 | 團隊實際錄影／剪輯／上傳YouTube及繳交網址；未捏造影片或版本標記 |

組員現在請依 [實測指南](a-completion-testing.md) 核對正常／異常操作並回報。若希望發布，指南有可複製的提交／推送／Ready PR授權句。A自有成果須另一位成員複核，再由A合併。

## 最終補驗與本機預覽

- 新門市首次日常入帳及盤點：已修正MySQL無小數秒欄位將微秒時間四捨五入到B的情況；未核對空帳使用B前一秒的無效盤點時間、reconciliation_required=true。真實B日常零銷售入帳→20件實盤後才成為usable，單案1 passed / 1.03s。
- 最後管理／履約／批次完整性、完整D Edge及效能：45 passed / 77.95s。此輪有一項PytestCacheWarning：cacheprovider.py:469無權建立`.pytest_cache/v/cache/nodeids`（WinError5）；不是產品或DB失敗。後續驗證使用`-p no:cacheprovider`，沒有改ACL或刪除快取來掩蓋問題。
- 補上履約HTTP版本要求後：`pytest tests/test_full_integration.py tests/test_fulfillment_concurrency.py tests/browser_a_completion.py tests/browser_fulfillment.py tests/browser_fulfillment_full.py -q -p no:cacheprovider` → **18 passed / 72.41s**，包含缺版本422、舊版本409、成功重試優先及兩連線操作。
- 全部十個Edge測試檔首輪：50 passed、2 failed / 313.40s；兩個失敗均因原D腳本仍等數字ID標題。更新為核對選中訂單編號後，兩案已在45項及18項補驗通過，沒有刪除案例或放寬業務規則。D既有Edge使用fixture_only工廠訂單，與A新增的真實C送單Edge證據分開。
- 最新1000商品／14000歷史列、真實提供者：生成**2.825s**；同環境十品項正式提交0.113–0.244s。CPU及軟體版本如上，沒有宣稱正式近千店容量通過。
- `scripts/rebuild_empty_test.py --confirm-empty-test`先確認system2_a_test業務資料空白，再移除空schema，從零套2ce34638ca9a→884e7a53a8c8；db check無差異、單一head。這是現有已安裝Python/MySQL環境的schema重建，沒有冒充新電腦安裝測試。
- 本機預覽已在127.0.0.1:5000啟動，PID32592、health=ok，APP_ENV=demo／MODULE_DEV空白。既有demo、.env、帳號與時鐘保留，沒有外部部署。
- 空schema重建後的最終完整回歸：`python -m pytest -q -p no:cacheprovider` → **370 passed / 360.34s，沒有warnings**。這是本次最後程式版本的完整結果，包含管理17項、批次完整性5種狀態、正式閉環4項、兩連線履約5項以及原有B/C/D與共用回歸。新版本前置條件下不同key競爭回200／409；同key仍兩個200、實際只一筆。
- 最後Node事件測試2 passed；management.js／fulfillment.js語法及git diff --check通過。Git另提示clock.py日後會LF→CRLF，不是差異錯誤。`pip check`沒有broken requirements。
