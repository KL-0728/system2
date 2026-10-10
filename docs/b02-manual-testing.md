# B02 畫面核對指南

本次只做 B02，不進 B03；不 commit／push／開 PR／合併。分支 feat/b-module，HEAD a139a7a **加本機未提交 B02 修改**；origin/main f2d5f67 已在歷史中。合約 v1、migration head 884e7a53a8c8 不變。

最終 AI 結果（a139a7a＋本機B02修改）：全套173 passed in 155.69s，其中B02服務／API52例；Edge6 passed in 28.00s（實際指令另加 -x，沒有skip）；環境PASS、db check無新增upgrade、node與diff檢查結束碼0。pytest／Edge沒有warnings summary，Git僅LF→CRLF提示。這些不是組員人工驗收結果。

## 1. 啟動這份 B checkout

先停止舊 Flask（在原終端機按 Ctrl+C），在新的 PowerShell 執行：

~~~powershell
Set-Location C:\Users\USER\Desktop\system2
git status --short --branch
git rev-parse --short HEAD
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
.\.venv\Scripts\python.exe -m flask --app wsgi inventory prepare-demo
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
~~~

預期：feat/b-module、a139a7a；demo／test 各 PASS，3308、head 884e7a53a8c8。prepare-demo 僅作用 B 自己的 system2_b*_demo；首次加合成資料並把未操作的 A03 起點推進一天，之後保留資料與時間，不重設、不倒退、不改密碼。本次 AI 已完成首次準備，重跑應提示保留既有資料。

若3308無法連線，先啟動 B01交接檔的既有3308資料目錄，不重新 initialize，也不用 A 的3307腳本。保留 .env；這份 checkout 用被 Git 忽略的 instance/b01-test-env.ps1 載入本機憑證，不能複製／提交它或貼內容。

瀏覽器開 http://127.0.0.1:5000/login，帳號 manager1，密碼是載入後的本機 $env:DEMO_PASSWORD（可在你自己的 PowerShell 查看，勿貼回聊天）。AI已用此值建立示範帳號；.env.example 的 managerps 不會改既有帳密。登入後開 **http://127.0.0.1:5000/store/data**。此 B 專用畫面可直接開，不改 C／A 的首頁選單。

預期：DEMO1、示範時間2026-10-09 21:20、本輪基準21:00／截止22:00。初始各品項帳面20、最近核對實盤2026-10-08 21:00，本日缺口2026-10-09，H不可用。若你之前已操作過，不會自動還原；先記錄目前帳面／批次／時間，不照初始數字宣稱通過。

模組模式 B 只為 D 未結來源提供受控供應者，持續有「非真實跨模組整合」標示；以下 CSV、盤點、完整性、異動均用正式 B 服務。B03計算、真實D收貨及A05／A06驗收尚未完成。「回補貨」目前可能顯示無可用建議，屬 B03 未開始。

## 2. 先驗證錯誤整批不寫入

1. 點頁首「銷售匯入」，下載「本店本日合成範例 CSV」；或使用 repo 的 demo/sales_sample.csv（只適用上述起點）。
2. 用文字編輯器另存 UTF-8 的錯誤測試檔，把 SKU02 改為 UNKNOWN；保留原檔。
3. 選「日常庫存入帳」、上傳錯誤檔、按「驗證整批」。
4. 預期：第3列 UNKNOWN_PRODUCT，提交按鈕停用；庫存仍20，沒有任何成功匯入。這次沒有新增批次。
5. 也可把某列 sold_qty 改成 -1／1.5／1000001，或把 store_code 改成 DEMO2。預期逐列顯示錯誤、整批不提交；不是部分成功。

CSV 欄位與順序固定：

~~~text
source_batch_id,store_code,sku,business_date,sold_qty,was_stockout,is_open
~~~

一批一個來源識別；日期 YYYY-MM-DD、數量0–1000000件、布林0／1；未營業且正數銷售、未結束的未來區間、重複 SKU＋日期都拒絕。上限512 KiB／2000列。

## 3. 歷史匯入 → 明確轉日常

1. 回原始正確檔，選「歷史預測資料（不扣庫存）」，取代批次ID留空，按「驗證整批」。
2. 預期：10列，區間2026-10-08 21:00→2026-10-09 21:00，每列庫存異動0，尚未提交。
3. 按「確認區間與庫存影響，提交整批」。記下回應的批次ID **HID**（實際ID，不固定為1）。
4. 預期：成功10列、合計差額0；飲料與雨衣帳面仍20、H不可用，仍列缺口2026-10-09；本日銷售顯示「僅歷史／未入帳」。
5. 點「以原批次重試核對」。預期回原批次ID與結果，沒有再次入帳、沒有第二批。
6. 在文字編輯器另存 daily.csv，把**全部10列**的 source_batch_id 改為 B02-2026-10-09-DAILY，其他欄位保留。
7. 選「日常庫存入帳」、daily.csv，取代批次ID填 HID，更正理由填「將未入帳本日歷史資料轉日常」。
8. 按驗證。預期飲料銷售2、異動-2；雨衣25、異動-25；其餘0。區間與上一批相同，不建立第二份有效銷售。
9. 按提交，記日常批次ID **DID**。預期10列、合計-27；飲料帳面18、H18；雨衣帳面 **-5**，H不可用、OPEN待對帳；其他帳面20、H20。本日均「日常已入帳」。
10. 原批次重試：帳面仍18／-5，批次ID不變。後續批次或盤點後重試仍回原成功快照；庫存卡片讀目前狀況。

模式切換不允許重扣。沒有更正批次／理由，換新的來源識別也不能直接覆寫相同區間；預期 SALES_EXISTS。若選已被2026-10-08盤點涵蓋的舊日期轉日常，預期 COUNT_COVERED，不能再扣種子庫存。整批更正要涵蓋目標批次所有有效列；不允許只取代其中一列。

## 4. 盤點差額、重試及同截止點修訂

1. 點頁首「盤點／修訂」，選 SKU01飲料。確認本日銷售已入帳、庫存卡片帳面18。
2. 截止點保留2026-10-09T21:00:00+08:00；實體總量20、不可販售0、理由「21:00實盤核對」；第一次不勾修訂。
3. 按「提交盤點差額」。預期修訂1、差額+2、目前帳面20、H20；原21:00帳面18保存，沒有直接覆寫／重套。
4. 點「以原盤點請求重試核對」。預期「沒有再次套用差額」、帳面仍20。
5. 同商品填實體21、不可販售0，確認「明確修訂」已勾選、盤點版本1；理由「核對漏算一件」，按提交。
6. 預期修訂2、只追加+1、目前帳面21、H21；一個主紀錄、兩個不可變修訂。原請求重試仍回各自成功結果，不追加第三次異動。
7. 把截止點改為20:30、再提交。預期 INVALID_COUNT_WINDOW，帳面仍21。改回21:00；不可販售填22而總量21，畫面拒絕提交，沒有改庫存。
8. 選SKU02雨衣：目前帳面-5。實體總量20、不可售0、理由「重新核對負帳面實盤」，第一次不勾修訂，提交。預期差額+25、目前帳面20、H20，負帳面對帳解除，不是靜默歸零。

延後提交保留截止後收貨的正式數字證據：自動服務／Edge測試使用受控收貨輸入呼叫正式B writer，帳面18→21:10收貨10得到28→21:20盤點20追加2得到30→修訂21追加1得到31。這是B服務的原子差額驗證，**不代表D收貨畫面已完成**；上述一般demo畫面沒有假收貨按鈕，沒有後續收貨時結果是20→21。

## 5. 跨盤點銷售更正不回改目前現況

在第4節盤點後進行，目標是第3節的 DID：

1. 另存 correction.csv，全部列的 source_batch_id 改為 B02-2026-10-09-CORRECTION；SKU01 sold_qty 改5，其他列保持原值。
2. 選日常模式、correction.csv、取代批次ID DID，理由「核對POS輸入，飲料銷售由2改5」。
3. 驗證預期 SKU01 差額0、明示已盤點涵蓋／建立待對帳；不減當前帳面3件。
4. 提交預期：飲料帳面仍21、本日銷售5；新增待對帳，H不可用、阻擋新送單；原批次與其快照保存。
5. 原批次重試不重建對帳、不扣庫存。
6. 飲料盤點勾明確修訂，實體21、不可售0、理由「重新核對21:00實盤並處理更正」，核對最新版本後提交。
7. 預期只追加0差額、飲料帳面仍21，sales_covered待對帳經有效盤點解除，H21。盤點首差額不再套一次。

如果先更正尚未被盤點涵蓋的區間，例如日常銷售2→5，則只再扣3，不扣5。服務測試另涵蓋此分支及負帳面以合法更正解除。已入帳資料不能降回歷史模式來避開差額。

## 6. 身份、網路與手機

- 用同一視窗 http://127.0.0.1:5000/api/auth/me 核對 username=manager1，從 stores 取 DEMO1門市id，最外層id是帳號id。
- 另開無痕視窗登入 manager2，核對username及stores後取得DEMO2門市id。manager1開 /store/data?store_id=DEMO2實際id 或 /api/inventory/status?store_id=該id 應404；manager2本店200。不要把CSV中的門市代碼當DB id。
- operator／admin不具店長盤點及匯入權限，開 /store/data 應403；未登入401；無CSRF的POST400。
- 開瀏覽器開發工具切390px／320px或用手機同等尺寸核對：商品名稱／件數、模式、提交按鈕及理由不橫向溢出；頁首區段連結可直達匯入／盤點，字體放大仍可操作。
- 若提交途中斷線，預期顯示「提交結果尚未確認」，鎖住新操作，重新整理保留原請求；網路恢復後按「以原請求重試」。成功則確認原批次／盤點，不重扣。不要換key猜測上次有無成功。AI Edge測試已模擬「後端成功、回應遺失」並核對此流程，不等同你已人工測過斷線。
- 兩個分頁先預覽CSV，另一頁有效變更庫存後，回第一頁提交：預期VALIDATION_STALE409，重新驗證整批；盤點舊版本VERSION_CONFLICT409。驗證token15分鐘以真實時間計，示範時鐘暫停也不延長新提交期限；成功重試不受此期限阻擋。

## 7. 重跑檢查及回報

先停止Flask，另在專案根目錄 PowerShell載入本機環境後執行：

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
$env:APP_ENV='test'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_inventory.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/inventory.js
git diff --check
~~~

真實Edge測試另需本機 .venv 的 Playwright與已安裝Edge；缺少會skip，不能宣稱通過。本次AI已在.venv安裝，不改共用requirements。截圖位於忽略的 instance/browser-check/b02-data-1280.png、b02-data-390.png、b02-data-320.png。pytest只用隔離test交易；兩連線競爭測試只建立／刪除確切自有fixture id，拒絕非空test資料庫。不用reset-demo、clean或重建schema。

請回報你實際執行的步驟、飲料／雨衣前後帳面、H、批次ID、錯誤文字與版本（a139a7a＋本機修改）。有warning保留完整類型／來源／訊息，不貼帳密。人工結果由你回報後才記錄。

可貼到聊天：

> 我是B，我已依B02畫面指南操作，結果為〈步驟、批次ID、飲料／雨衣數字及H／錯誤文字〉。請記錄，仍停在B02，不commit、不push、不開PR，不進B03。

