# A 收尾：整合版實測與交付

2026-10-13；開發分支 `chore/a-project-completion`，基準 `b45cccb`。D 已由 PR #6 合併，來源 head `dd39baf`。A在本次對話明確授權納入既有修改、完整檢查及直接推main；本次依此授權執行，沒有部署。最新结果及版本核對方式見 [檢查報告](project-review-2026-10-13.md)。

更新程式後請在原Flask終端按Ctrl+C，再依下列命令啟動最新版。不要沿用舊程序的記憶體內容或依歷史PID停止程序。網址 http://127.0.0.1:5000/login；修改登入驗證後，既有登入須重新登入。

## 啟動既有環境

在 `C:\Users\user\Desktop\system2` 的 PowerShell 執行。先停止舊 Flask，保留 `.env` 與 demo 資料；不要重設或再次 seed。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_a_mysql.ps1
.\.venv\Scripts\python scripts/check_environment.py
$env:APP_ENV='demo'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

預期兩個 DB 都 PASS，migration `884e7a53a8c8`。開啟 http://127.0.0.1:5000/login。帳號 `admin`、`operator`、`manager1`、`manager2`、`bcmanager` 的密碼使用建立帳號時本機 `DEMO_PASSWORD`；改 `.env` 不會改既有密碼。本輪唯讀檢查已確認 BCDEMO（id 5）十個商品各有可售20、不可售0；目前業務時間是2026-10-08 21:00（台北）。後續操作若改資料，應以畫面當下數值為準。

## 管理者核對

1. `admin` 登入 → 點「管理設定」或 http://127.0.0.1:5000/admin。可切換商品、門市、帳號及門市商品政策。
2. 選商品「飲料」，只修改名稱並儲存 → 顯示已儲存；相關門市舊預覽失效，庫存數量不變。若修改箱入數，各門市政策會新增版本，歷史訂單維持舊箱入數。
3. 選一筆門市商品政策，把安全庫存10改為15 → 新版本增加1，舊政策保留；回門市重新產生建議。H20、mu20、L1、箱6的飲料應由30變為36。這是新建議，舊訂單仍保留原值。
4. 開兩個分頁修改同一筆設定；第一頁先儲存，第二頁儲存舊版本 → 明確提示設定已更新，不覆蓋第一頁。重新整理後再修改。
5. 帳號頁可新增店長並指派門市；停用帳號後，该帳號下一次請求要求重新登入。不能停用自己的管理帳號。新增門市商品的帳面0是**未核對空帳**，必須入帳與盤點，不能當有效庫存送單。
6. 「準備今日配送輪次」選門市 → 建立本轮1–3日及政策交期轮次；再按一次新增數0，不改既有訂單。
7. 操作紀錄填 `management.policies.save` → 只看到政策修改紀錄，包含前後值、業務／伺服器時間；沒有密碼或密碼雜湊。
8. 用 `manager1` 或 `operator` 登入後直接開 `/admin` → 403；不能只以選單隱藏當權限證據。

## 真實送單、出貨與收貨

此段請用未修改政策的 **BCDEMO / bcmanager**；若已用過，先核對未結單與實際庫存，不假定仍是初始30件建議。不要重設另一位組員的資料。

1. `admin` 在管理頁將示範時鐘推進至 `2026-10-08 21:01` 並暫停 → 每頁顯示21:01。設回21:00應被拒絕。收貨時間須在最近盤點基準之後，避免同一截止點重複入庫。
2. `bcmanager` 登入 → 先開 http://127.0.0.1:5000/api/auth/me，核對 username 與 stores 內的 BCDEMO id；最外層id是帳號id。
3. 先從首頁「準備補貨建議」或「補貨」的計算頁重新產生本輪建議，再使用該建議開始訂購；不沿用D合併前的快照 → 原始案例十品項各30件。首次使用須確認說明，之後不重複要求。本輪唯讀檢查BCDEMO正式訂單0張；首次送單後此數字會改變。
4. 「儲存並預覽本單」 → 十品項預填、總量300，無重要例外時只有一個逐單確認框。勾選後「確認數量並送出補貨單」 → 得到訂單編號；狀態待統家接單，庫存仍20。
5. 登出後 `operator` 登入 →「前往接單履約」，選BCDEMO與剛才編號。選飲料「完整接單」承諾30、到貨2026-10-09 21:00；「原訂出貨（非補送）」填30 → 原訂量仍30，批次待收30。
6. `bcmanager` 登入 →「收貨」，選同一張訂單。核對30、可售28、損壞2、短收0，原因「外包裝破損，已隔離處理」 → 實體50、不可售2、可售48；已核對部分不再列有效在途，損壞差異可追蹤。
7. 重新整理 → 該批待核對0，不再提供同批30件收貨。API同請求重送只回原結果；自動測試另驗同鍵不同內容409與兩連線同時收貨。
   在兩個分頁開同一筆待接單資料，第一頁接單後，第二頁提交原畫面操作 → 409「供貨或收貨資料已更新」，不能覆蓋第一頁。按「重新整理」後再核對。直接API呼叫須傳訂單version作expected_version；成功收貨原請求重試仍回同筆結果。
8. `manager2` 登入，先查 `/api/auth/me` 核對是DEMO2，再取用BCDEMO訂單API → 404；不能讀取或收貨。手機390px／320px核對無橫向溢出。

## 正常補貨三人計時（必須由真人填寫）

三位未參與開發者各自操作無重要例外的十品項案例，先完成首次說明，準備有效銷售／盤點；從首頁取得訂單編號。每人各自兩分鐘內、口頭協助0次才符合spec。先前已送出的單會影响U/C，須為每位測試者準備獨立案例，不能用同一店連送三次假裝相同起點。AI瀏覽器操作不能代填此表。

| 測試者 | 設備／瀏覽器 | 測試版本 | 秒數 | 錯誤 | 協助次數 | 結果 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 待填 | 待填 | 待填 | 待填 | 待填 | 未執行 |
| 2 | 待填 | 待填 | 待填 | 待填 | 待填 | 未執行 |
| 3 | 待填 | 待填 | 待填 | 待填 | 待填 | 未執行 |

## 自動重測

停止 Flask，另在根目錄 PowerShell 執行。測試只用 `system2_a_test`，不清 demo。

```powershell
.\.venv\Scripts\python scripts/check_environment.py
.\.venv\Scripts\python -m pytest -q
node --test tests/ordering_ui.test.cjs
.\.venv\Scripts\python -m pytest tests/browser_a_completion.py tests/browser_fulfillment.py tests/browser_fulfillment_full.py -q
.\.venv\Scripts\python -m pytest tests/performance_integration.py -q -s
```

期望全部通過；Playwright缺少或Edge未安裝時不可將skip當通過。效能目標只適用紀錄的測試環境，不代表正式規模部署。新環境重建測試僅可對空的獨立test DB使用 `scripts/rebuild_empty_test.py --confirm-empty-test`，不要指向demo。

## PR 與最後交付

本次使用者已授權A直接推main，不再要求另一個發布許可。下方PR文字保留供團隊後續參考，不能當成本次仍需停下等待的步驟。真人實測與影片仍依實際結果記錄。

人類實測若失敗，回報版本、步驟、實際數值、預期數值及錯誤文字；不包含憑證。A 的功能由另一位成員複核，再由 A 合併。

可貼到聊天的下一句：

> 我是A，已按 a-completion-testing.md 完成人工核對，結果為〈逐步結果〉。請只提交本次A收尾檔案、推送 chore/a-project-completion，建立Ready PR，附實際自測與尚未完成驗收項目，不合併。

PR標題：`feat(A04-A06): 完成管理設定、真實履約整合與效能優化`

PR內文：

```text
已合併的D模組尚未出現在日常入口，管理設定亦缺少操作介面。此變更新增管理者商品／門市／帳號／政策、版本衝突保護、稽核與示範時鐘控制，接上店長收貨及統家履約入口。
政策追加新版本並使舊預覽失效；歷史快照保留。新門市商品以未核對空帳開始。庫存完整性與D未結來源改用批次查詢，修正MySQL取得門市鎖後仍讀舊收貨／出貨資料的問題。
驗證：填入docs/a-completion-report.md實際結果；含正式B/C/D閉環、回滾、兩連線併發、Edge桌面／手機、1000商品效能及migration。
介面：唯讀DTO v1不變；InventoryService新增選用get_integrities，舊提供者仍走get_integrity。履約HTTP寫入依spec補上expected_version，前端已同步；成功冪等重試優先。未增加依賴或migration。
真人三人計時、最終V逐項人工確認、教學錄影與YouTube繳交仍依實際證據列待辦。
來源：D PR #6，head dd39baf，合併b45cccb；B/C歷史來源见既有交接。
```

影片腳本見 `demo/video-script-zh.md`。正式可運行版本標記應在複核／合併及必要驗收後建立；影片上傳與繳交網址须由人類完成，不捏造連結。
