# B01–B05 完整本機畫面核對（B05 收尾）

被測版本：feat/b-module，f5867b6bcd30d681e17070f831b99b18ee2eb624 加本次未提交 B05 修改。只核對 B 模組，不代表 A05／A06 真實閉環完成。AI 自動測試與下列人類操作分開記錄；本次尚未收到 B 的人工結果。

## 準備與身份

在 C:\Users\USER\Desktop\system2 的 PowerShell 操作。若有舊 Flask，先在它的終端按 Ctrl+C；保留所有未提交修改。下面只使用自己的隔離 DB，不 reset、不重設密碼或時鐘。

~~~powershell
Set-Location C:\Users\USER\Desktop\system2
git status --short --branch
git rev-parse HEAD
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi inventory prepare-b05-demo
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
~~~

預期分支 feat/b-module、HEAD f5867b6、demo/test 兩行 PASS，head 884e7a53a8c8。B05DEMO 已建立（本機門市 id=6），重跑 prepare-b05-demo 保留既有庫存／銷售／密碼／時鐘。初次建立只新增自己的合成案例；舊 B05 合成案件缺期限時，只補存責任、政策期限與版本並記 audit。其他門市不變。資料曾被人工操作後，這個指令不把它還原成起始值；勿自行清空 DB。

登入 http://127.0.0.1:5000/login ，帳號 **b05manager**，密碼取自本機私有 instance/b01-test-env.ps1 的 DEMO_PASSWORD。可在另開、未分享的 PowerShell 載入該檔後看 $env:DEMO_PASSWORD；不要把值貼回聊天或提交 Git。新增帳號時已設定這個密碼，重跑不更換既有帳號密碼。

在同一視窗開 http://127.0.0.1:5000/api/auth/me ，確認 username=b05manager；stores 中 B05DEMO 的 id 才是門市 id，不能使用帳號 id。以下以本機已核對的 store_id=6 為例。若身份不同，先登出再登入。

資料：http://127.0.0.1:5000/store/data?store_id=6
補貨：http://127.0.0.1:5000/store/replenishment?store_id=6

本機業務時鐘保持 **2026-10-09 21:20 Asia/Taipei**，盤點截止點 **2026-10-09T21:00:00+08:00**，受理時間21:00–22:00。若頁面顯示不同輪次，先回報，不移動共用時鐘配合案例。停用 B 模組的服務可能回404；上述正確身份、MODULE_DEV=B 的 B 頁面仍404時，檢查是否連到舊 Flask 與 URL，保留錯誤全文／版本回報。

## 依序操作與預期結果

下列寫入會保存在你自己的 B05DEMO，請依序做。種子收貨是合成 B 庫存來源，不是 D 真實收貨；現在的資料量是21:00帳面加已入帳後續異動，不是即時POS。

1. **確認起始資料**：開「資料管理」，看庫存、銷售狀態、最近批次、對帳及唯讀異動。

| 商品 | 帳面總量／不可售 | H | 核對 |
| --- | --- | --- | --- |
| SKU01 飲料 | 32／2 | 30 | 21:00盤點20；21:10合成收貨12，其中2不可售 |
| SKU02 雨衣 | -5／0 | 不可用 | 真實B日常入帳25，negative_book待處理，負值不截成0 |
| SKU03 泡麵 | 30／0 | 不可用 | 真實B盤點20後收貨10；盤點涵蓋的銷售更正0→1只改預測並建立sales_covered對帳 |
| SKU04 衛生紙 | 8／0 | 8 | 七日預測缺2026-10-03；庫存可用、預測不足 |

對帳有兩筆 OPEN，顯示店長責任、建立／政策期限及案件版本。預設24小時期限為2026-10-10 21:20；逾期僅顯示狀態，仍須實際處理。種子的日常來源已入帳，不需再用下載的全店本日 CSV 重扣。

2. **報廢及重試**：「損壞品報廢／退回」選 SKU01、報廢1件，時間維持21:20含時區、來源沿用自動唯一值，填理由，按「核對數量後登記實物移出」。

   預期32／2→31／1，H仍30；唯讀紀錄新增 disposal(-1,-1)，保留 receipt(+12,+2)的原始來源。按「以原異動請求重試核對」，預期「沒有再次扣庫存」，仍31／1，沒有第二筆報廢。

3. **錯誤與退回**：改「退回損壞品」，先填3件，理由照填，按提交。

   預期 INSUFFICIENT_DAMAGED_STOCK，庫存仍31／1。改1件再提交，預期30／0、H30；新增 return(-1,-1)，原收貨不改。再次按原異動重試仍30／0。0／小數件數、不可售超過總量與舊版本都不能當成成功提交。退回只記錄實物離店，退款不是B功能。

4. **負帳面對帳**：找到 SKU02 的 negative_book 案，按「以21:00盤點處理此對帳」。核對上方顯示案件號／版本及商品雨衣，填21:00實盤總量10、不可售0、理由；第一次盤點不勾「明確修訂」。按「提交盤點差額」。

   預期差額 **+15**，帳面-5→10、H10；案件變「已處理」，顯示完成者id／時間；展開「原處理紀錄（唯讀）」有 count_id、revision_id、request_key、理由與原期限。按「以原盤點請求重試核對」仍10，不再加15。不能只勾一個結案框就清除阻擋。

5. **盤點涵蓋銷售更正對帳**：選 SKU03 的 sales_covered 案，按相同按鈕；保持21:00截止點，實盤總量20、不可售0，**勾選明確修訂**，核對最新盤點版本並填理由，提交。

   預期盤點修訂2、差額 **0**、目前帳面仍30、H恢復30；21:10收貨10保留，不被覆寫成20；銷售更正為1，案件已處理。原請求重試仍30／修訂2；換新請求但不勾修訂會拒絕已有盤點。尚缺本日日常入帳的商品不能用盤點繞過該缺口。

6. **七日模型與快照（B03）**：開「補貨計算」，選最早配送輪次L=1，各商品模式model，按「產生並保存計算快照」。

   預期 SKU01／02／03 建議 **24／42／15件**；SKU04缺一日，建議顯示「無法計算」而非0。核對七日來源、21:00基準、產生時間、現貨、箱入數及警示。把飲料最終量改31後按「依上方輪次與各品項最終量試算」，預期 INVALID_PACK，不自動改成36。改回24可試算。試算不建立訂單、不扣庫存，不覆寫保存快照；配送L=3另看提前天數及缺貨風險。記下保存快照id。

7. **人工預測（B04）**：展開「計算模式／人工值／歷史註記」，SKU04選manual，日需求填 **5.125**、理由填核對依據，按該品項保存人工值。

   預期最新修訂／操作人／期限顯示；先不勾本輪確認就產生快照，預期未確認拒絕。主動勾確認再產生，預期 μ=5.125、目標20.25、raw12.25、建議 **13件**。小數最多三位；5.1234拒絕，保存值不被覆寫。有效期使用政策manual_valid_days，預設7日的第7日21:00截止；每次新產生／試算都須本輪明確確認。舊修訂只供追溯。這些操作提高門市版本，舊快照能讀但不可拿舊版本直接試算。

8. **特殊直接訂購（B04）**：SKU04改direct；需要日期2026-10-10、需要1000件、理由「社區活動需要一千件衛生紙，已核對件數」、安排「到貨後直接交付活動單位」、直接量1000，再產生快照。

   預期 μ／S／raw／建議為null／「無法計算」，無模型曲線；最終量1000，保守容量 **H8+Q1000=1008**，有 DIRECT_ORDER、SPECIAL_DEMAND、CAPACITY、LARGE_QUANTITY 警示。need_qty1000不再加一次變2000。改最終量1200再試算，保守1208；讀取剛保存的原快照仍1000。0件或缺需要日期／理由／存放安排拒絕，庫存缺口也不能靠direct繞過。B畫面只做計算／試算，正式送單由C流程處理。

9. **CSV整批驗證、歷史與冪等（B02）**：回資料管理，匯入模式選「歷史預測資料（不扣庫存）」、取代批次留空。先選 demo/b05_invalid_sample.csv，按「驗證整批」。

   預期 UNKNOWN_PRODUCT，整批未寫入、提交不可用；正確SKU04那一列也未寫入，帳面H仍8。再選 demo/b05_historical_sample.csv、驗證整批：SKU04、2026-10-03、銷售20，差額0；按「確認區間與庫存影響，提交整批」。預期新批次1列／差額0、H8保持。按「以原批次重試核對」仍差額0、同一批次；重新驗同source_batch_id顯示BATCH_EXISTS，不能新建重扣。回補貨，將SKU04切回model／刷新版本，產生新快照，預期平均20、建議 **42件**。舊快照仍保留原缺日來源。

   日常整批入帳、更正與歷史轉日常的獨立畫面案例及錯誤說明見 [B02指南](b02-manual-testing.md)；七日模型／L3見 [B03指南](b03-manual-testing.md)。這些歷史指南使用各自案例身份，不能把B05的store_id與它們混用。B05種子已透過正式B日常／更正服務建立第1步的數字，未把合成D收貨說成真實D。

10. **身份與手機**：同一b05manager視窗開 http://127.0.0.1:5000/api/inventory/status?store_id=1 ，預期404拒絕其他門市。回自己的資料頁，在Edge開發者工具改390／320px與20px字體，核對表單／對帳／唯讀來源無水平溢出，按鈕可操作。一般operator在B資料／對帳API應403（隔離測試已驗證）；不得把未由你人工登入操作的其他身份填成已驗收。

## 可重跑檢查與真實整合界線

停止Flask或另開終端皆可；測試共用隔離test DB，請依序執行，不同pytest程序不要同時跑。manual兩個腳本只在尚未人工改動的B05起始資料跑；數字腳本所有服務寫入最後rollback，比對全部36表筆數、庫存／門市／銷售版本與時鐘；改動過起始案例會拒絕，不能重設資料為了讓它過。

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
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

實際完整測試結果見 [B交接](handoffs/B.md) 最新B05列。兩個既有凍結合約案例需要A協調；不可把非全綠標成全通過。MODULE_DEV=B 的 D open_orders 仍為受控替身；正式B↔C的隔離測試證據與真實D閉環分開。真實 C 送單／D批次到貨／不可售移出／未結量／A管理與全V驗收留A05／A06。

## 回報與交付

請現在依本指南實測，先不commit／push／開PR。人工步驟會保存你的示範資料；重試請使用畫面的「原請求」按鈕，勿改來源鍵掩蓋結果不明。若遇失敗，保留步驟、商品、實際數字／預期數字、URL、username、錯誤全文、版本；不要貼密碼。

貼到聊天的下一句（填實際結果）：

> 我是B，已核對feat/b-module的f5867b6＋本機B05修改。報廢重試【結果】、退回越界【結果】、負帳面盤點10／差額15【結果】、涵蓋更正保留30【結果】、模型24／42／15【結果】、人工5.125→13【結果】、直接1000→容量1008【結果】、歷史CSV不扣庫存／重試【結果】、手機與權限【結果】。失敗步驟與錯誤【內容】。請記錄，先不提交推送。

[本機PR內文](handoffs/B-pr.md) 已備妥，人工結果待填，因此保持Draft。人工確認與兩項共用測試協調後，若要發布，另明確授權「請提交並推送feat/b-module，依B-pr.md開Draft PR交A，不合併main」。僅說Push並不授權合併。A協調共用測試及真實整合，依agent.md確認可Ready後再改狀態。本次未建立PR或提供虛構PR網址。
