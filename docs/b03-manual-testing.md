# B03 畫面核對指南

本次只做B03；不進B04、不commit、不push、不開PR。被測版本為 feat/b-module 的 5ca02631e02212826d2e923d30fb1c11077f14a0 加本機未提交B03修改。最新main f2d5f67及 a03-parallel-v2 已在分支歷史中，合約v1及migration不變。

## 在這份 checkout 啟動

若有舊Flask正在執行，先在它的終端按 Ctrl+C，再於專案根目錄啟動新的程式。使用Flask＋MySQL，不用Live Server。B自己的MySQL3308及兩個資料庫已準備；不重新seed-demo、不reset、不覆寫.env。

~~~powershell
Set-Location C:\Users\USER\Desktop\system2
git status --short --branch
git rev-parse --short HEAD
. .\instance\b01-test-env.ps1
$env:APP_ENV='demo'
$env:MODULE_DEV='B'
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi inventory prepare-b03-demo
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
~~~

預期分支 feat/b-module、HEAD 5ca0263、B03檔案尚未提交；環境兩行PASS，head 884e7a53a8c8。prepare-b03-demo 已於本次執行：獨立B03DEMO門市id=3、帳號b03manager。再次執行只報既有資料保留；既有DEMO1／DEMO2、時鐘、庫存及憑證不變。指令限定APP_ENV=demo、MODULE_DEV=B及system2_b*_demo資料庫。

本機業務時間目前2026-10-09 21:20（Asia/Taipei），暫停；生成及試算限定本輪21:00–22:00。若之後已推進時鐘，不將它倒退：舊快照仍可看，新輪次需要有效配送輪次／七日資料及完整入帳。不要為重現數字重設既有資料。

開啟 http://127.0.0.1:5000/login，登入 **b03manager**。密碼取自本機DEMO_PASSWORD；需要查看時，在另一個本機PowerShell載入環境後執行：

~~~powershell
. .\instance\b01-test-env.ps1
$env:DEMO_PASSWORD
~~~

只在你自己螢幕查看，不貼到聊天／截圖／Git。舊manager1／manager2密碼未修改；b03manager建立時使用此值，修改環境變數不會自動更新已建帳號。

登入後在同一瀏覽器開 http://127.0.0.1:5000/api/auth/me，核對username=b03manager，stores內的門市code=B03DEMO、id=3；帳號id與門市id不同。再到 http://127.0.0.1:5000/store/replenishment 。

## 逐步操作與預期

1. 頁首應為B03DEMO「B03合成計算核對門市」，顯示本輪B=2026-10-09 21:00、業務時間21:20、截止22:00。持續明示未結來源為受控替身，真實D整合尚未驗證。
2. 配送輪次選2026-10-10 21:00、L=1，點「產生並保存計算快照」。應顯示新快照編號、原始產生時間、資料涵蓋時間、風險評估時間與保護期至2026-10-11 21:00。本次AI已保存#1；你再次生成會新增另一筆快照，這不是正式訂單，也不扣庫存。
3. 核對下表。合成盤點基準已核對於B，銷售是明示歷史輸入、不重扣；正常受控未結來源是空集合，故O=0，飲料為42件而非規格有O=12的30件案例。30件案例由B正式計算＋受控未結提供者在測試中核對。

| 商品 | H | 七日平均 | S | Q原始 | 建議 | 警示 |
| --- | --- | --- | --- | --- | --- | --- |
| SKU01飲料，箱6 | 8 | 20 | 50 | 42 | 42件 | PRE_ARRIVAL_STOCKOUT：新貨到達前可能缺貨 |
| SKU02雨衣，箱1 | 60 | 0 | 10 | 0 | 0件 | ZERO_SALES資訊：確認安全庫存 |
| SKU03泡麵 | 8 | null／無有效預測 | null | null | 無有效建議 | FORECAST_INSUFFICIENT；最終量欄停用 |

4. 展開飲料「計算公式與參數」及「七日銷售與入帳來源」。日期2026-10-03…10-09，銷售18、22、20、19、21、20、20，總和140÷7=20。不拿更早資料補缺檔；泡麵缺2026-10-03，顯示缺檔，不顯示0。
5. 展開飲料「已承諾＋本次試訂」：B期末8；10-10 21:00先預測銷售20、失去銷量12，再加本次候選42，期末42；10-11銷售20後22。失去銷量不是欠貨，不在翌日再扣12。待接單版在本機空來源案例相同；在受控pending服務測試中，U12、C0、建議30，已承諾版到貨後30、含U版42。期外／爭議／逾期來源保留RISK，不扣近期需求。
6. 飲料試算最終量填 **31**，點「依上方輪次與各品項最終量試算」。出現INVALID_PACK及可選上下界；輸入仍31，沒有自動改成30或36。此錯誤不能靠重要例外勾選繞過，正式送單由C處理。
7. 配送輪次改為2026-10-12 21:00、L=3，飲料最終量改 **1000**，再試算。B仍10-09 21:00；保護至10-13 21:00；μ20、S90、Q原始82、整箱建議84。1000不是箱6整數倍，應同時看見INVALID_PACK、LARGE_QUANTITY、DEVIATION、CAPACITY及PRE_ARRIVAL_STOCKOUT；輸入仍1000。容量看實際到貨時先扣銷售再加到貨，不直接H+Q，也不靜默截量。
8. 若要測合法四位數單位，改回L1，雨衣最終量填 **1000**。試算顯示大量／偏離／容量警示，雨衣沒有INVALID_PACK，輸入仍1000。這只試算，未送單；特殊直接訂購與人工預測留B04。
9. 點「讀取原快照」。即使剛改過輪次或數量，應讀回原L1、飲料42、雨衣0、當時來源／時間／警示；原快照未被試算覆寫。重新整理再選原編號仍可讀。生成新快照不修改舊快照。
10. 開 http://127.0.0.1:5000/store/data ，核對本店飲料帳面/H8、雨衣60、泡麵8；上面生成／試算皆未異動庫存或版本。由此頁「補貨計算」連結可返回計算頁。
11. 手機／Edge響應式寬度390及320px，主畫面不橫向溢出；明細表只在自身區塊內捲動。重要警示不需展開即可看到。
12. 權限錯誤：先登出，登入manager2，再開 http://127.0.0.1:5000/store/replenishment?store_id=3 →404；operator→403。每次在同視窗/api/auth/me先核對身份。admin可指定門市id讀取。未登入→401。

## 檢查命令與範圍

~~~powershell
. .\instance\b01-test-env.ps1
$env:PYTHONIOENCODING='utf-8'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest tests/test_replenishment.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests/browser_replenishment.py tests/browser_inventory.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
node --check app/static/js/replenishment.js
git diff --check
~~~

最終全套：2 failed, 219 passed in 146.51s；221例中B03新增48例全部通過，兩個失敗均為下列未改動的共用測試。真實Edge回歸9 passed in 26.29s（B03 3＋B02 6，無skip）；持久化demo真實Edge核對PASS。環境兩行PASS，db check：No new upgrade operations detected，node --check與git diff --check結束碼0。

兩個舊共用測試仍需A協調，不宣稱全套綠燈：tests/test_contracts.py 的 test_no_silent_fallback 仍假設runs未實作而預期503，B03現在註冊正式runs；test_independent_module_boot[C-expected1] 的共用開發頁硬找controlled-test-v1／id0，但已註冊正式B提供者不會被替身覆蓋，正式B不接受假快照。未修改凍結測試、合約或A／C頁面來遷就。A應修正缺服務測試的設定前置及開發頁對提供者／快照的選擇，不改v1資料意義。其餘相容測試與真實B→C草稿讀取證據見交接。

B03的七日品質、公式、U/C/RISK、固定B／L、時序／容量、不可變快照是B正式服務；D來源是受控輸入。真實D分段唯一性、正式送單／履約及產品整體V驗收留A05／A06。人工預測／歷史活動資訊／特殊直接計算留B04，完整報廢退回／對帳留B05。

對應V01–03、V12–14、V20、V22–24、V27、V29、V31、V39、V41、V49的B03部分證據，非全部V流程通過。

## 404／失敗回報

本次正確畫面是 /store/replenishment，API為 /api/replenishment/runs/{實際id}。任意未知地址、未啟用/modules/c/或跨店404不能只靠HTTP_404 JSON判斷原因。保留完整網址、身份及步驟；確認使用新Flask、MODULE_DEV=B和APP_ENV=demo。/health應status=ok；登入後本頁應200。favicon.ico的404不影響功能。

在聊天回報：

> 我是B，我已核對B03，版本5ca0263＋本機B03修改，快照〈編號〉；飲料／雨衣／泡麵為〈數字〉，L3與1000試算〈警示〉，31件〈錯誤〉，原快照〈結果〉，手機／權限〈結果〉。請記錄，仍停在B03，不commit、不push、不開PR，不進B04。

失敗時附步驟、完整URL、/api/auth/me身份、實際與預期差異、錯誤文字／request_id；不附密碼、連線或金鑰。AI的Edge結果不代填B人工通過。現在請照本指南實測；先保留本機修改，等你指示才做下一階段或發布。
