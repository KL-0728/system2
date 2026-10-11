# 全專案檢查與優化

2026-10-11；A整合檢查，起始main／origin/main為bd906a0，任務分支fix/a-project-review。使用者授權檢查、優化，完成後提交並放入main。D尚未交付，本輪不代做D履約，也不判定完整A05／A06或V01–V50通過。

## 查到的問題與處理

| 視角 | 問題 | 改善 |
| --- | --- | --- |
| 店長操作 | 首頁沒有正式快照時只有說明，缺少資料準備入口；計算後沒有返回訂購的入口 | 首頁提供準備建議；計算頁提供使用最新建議訂購，明示試算修改不會自動帶入草稿 |
| 畫面與可讀性 | 各頁選單重複且資料管理入口不一致；計算摘要使用H／U／C等符號、配色未跟上共用樣式 | 共用門市選單，保留門市id、目前頁標示與手機換行；摘要使用中文，細節保留公式，採既有靛紫色系 |
| 資料來源 | B已保存列表包含工廠／受控快照，讀取卻被正式B拒絕 | 只列正式B可讀取的模型版本；既有快照不刪除或改標來源 |
| 運作 | 計算頁初始按鈕可能在資料載入前可點；處理期間理由文字仍可編輯 | 初始禁用操作，載入後才啟用；處理期間一併鎖定textarea |
| 查詢與處理量 | 10個商品分別查七日銷售與最新人工值，各10次；最新單筆查詢未設SQL限制 | 銷售與最新人工值各一次批次查詢；按設定時間及id取每商品最新值，最新單筆增加LIMIT 1 |
| 文件與狀態 | 任務表仍寫B未開始、C補修未提交；README仍描述C追加受控B快照；首頁說正式庫存尚未串接 | 校正目前main狀態及真實B／C来源；保留歷史紀錄與完整產品驗收的未完成狀態 |
| 精簡 | 多頁重複維護同一選單與CSS，批次查詢後留下未使用import | 集中為store/_nav.html與共用CSS，移除被取代查詢及未使用import |

沒有新增依賴、資料表、migration、DTO或產品規格。庫存完整性、門市鎖、版本檢查、確認及冪等規則保留。既有測試、示範資料、遷移與交接紀錄各有用途，未為減少檔案數刪除；本機.env、venv、MySQL資料及.review亦保留。

## AI驗證

Python3.12／MySQL9.6 InnoDB 3307，demo與test隔離，migration為884e7a53a8c8。資料庫啟動前先唯讀檢查，確認未啟動後只啟動既有實例，不初始化或重設。

- 原main回歸：323 passed in157.09s。
- 修正前4個新增檢查全部重現：首頁缺入口、列表混入工廠來源，以及generate／context各有10次銷售＋10次人工值查詢。
- 第一輪修正：103項相關MySQL測試通過；同10商品各類輸入查詢降為一次，兩類合計20→2。這是查詢次數改善，不等同整體速度提升90%，亦非1000商品完整效能驗收。
- 第一輪新Edge流程：手機390／320px通過，1280px重現初始按鈕早於載入完成的競態；已修初始禁用，再驗全套畫面。
- 最終完整MySQL：`python -m pytest -q -p no:cacheprovider`，327 passed in205.20s，沒有skip或warning。包含原權限、交易、版本、冪等及MySQL併發案例。
- Edge全套首輪為1 failed、42 passed in135.93s：唯一失敗是新1280px腳本沒有等待登入跳轉，並非後端或畫面錯誤。加入等待後只重跑新流程：3 passed in14.41s。40項既有案例＋3項新流程皆已有通過證據；已查看桌面及手機截圖。
- `node --test tests/ordering_ui.test.cjs`：2 passed；全站JavaScript語法、92個Python檔語法、10個Jinja模板、25份Markdown本機連結及`git diff --check`通過。
- `APP_ENV=test`執行`flask db check`：No new upgrade operations detected。既有BCDEMO十商品唯讀options量測0.015秒，兩類各一次查詢；讀取交易回滾。

Edge使用正式B計算／完整性與正式C草稿／確認／送單；D未結量使用受控提供者。其他既有C瀏覽器案例仍使用明示B／D測試供應者，兩類結果分開判讀。所有寫入限定隔離test DB，不以此宣稱正式D收貨或庫存閉環通過。

## 組員可照做的實測

在C:\Users\user\Desktop\system2，先停止舊Flask（Ctrl+C），另開PowerShell。使用既有BCDEMO／bcmanager；密碼取建立此合成帳號時的本機DEMO_PASSWORD，勿將私人憑證貼到聊天。不需要reset-demo或再次seed-demo。

```powershell
$env:APP_ENV='demo'
$env:MODULE_DEV='C'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

1. demo／test皆PASS後，開http://127.0.0.1:5000/login登入bcmanager並Ctrl+F5。同視窗http://127.0.0.1:5000/api/auth/me應為bcmanager，stores含BCDEMO（此checkout現有id5；其他checkout以實際回應為準）。首頁選單有補貨／訂單／資料管理，收貨停用。
2. 從資料管理核對庫存，再點上方補貨。沒有正式建議時應顯示準備入口；已有建議時可開工作台。首頁不再說正式庫存尚未串接。
3. 開http://127.0.0.1:5000/store/replenishment?store_id=5，已保存列表應只含正式B快照，讀取不出現PROVIDER_MISMATCH。既有BCDEMO飲料H20、日需求20、SS10、L1、無未結量時建議30件。按使用最新建議訂購，應進入C工作台；此連結不會建立或送出訂單。
4. 若需重新產生快照，僅在示範業務時間21:00–22:00且庫存有效時操作；載入前按鈕禁用，產生期間理由欄位也禁用，完成後恢復。試算不改庫存；修改試算量不自動帶入C草稿。
5. C工作台按儲存並預覽本單，未勾選總覽／必要重要例外時不能送出。一般單核對後送出會建立正式訂單；只有要實際新增一張本機示範訂單時才操作。列表顯示待統家接單，庫存不因送單增加，D正式收貨仍未開放。
6. 以390px與320px寬度、125%字體核對首頁、資料頁、計算、預覽與訂單選單：可換行、無整頁橫向溢出、目前頁標示正確。manager1存取BCDEMO應404，不能看到另一門市資料。

若想只重跑隔離自測而不新增demo快照／訂單，在另一個PowerShell執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_project_review.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_project_review.py -q -p no:cacheprovider
node --test tests/ordering_ui.test.cjs
```

預期後端4項、新Edge3項與Node2項通過；Edge需本機Playwright與Microsoft Edge，缺少時不得把skip寫為通過。錯誤回報附版本、身份、網址、失敗步驟與實際／預期差異。人類實測由組員回報後另記；本轮已授權提交、合入main及推送，不部署。
