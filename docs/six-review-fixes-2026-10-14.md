# 六項複查修復與實測交接

本次依使用者明確授權，按 A 跨模組整合修復處理，分支 `fix/a-six-review-issues`，起始 `main`／`origin/main` 為 `df242cf`。保留既有資料與功能，不新增資料表、不修改已發布 migration、不啟用模組供應者替身。測試資料只使用既有獨立 `system2_a_test`，外層交易隔離；沒有重設 demo 資料。自動測試結果與人工驗收分開記錄。

| 問題與原因 | 修復與主要檔案 |
| --- | --- |
| 銷售匯入把啟用旗標當作商品存在條件 | `app/services/sales.py` 依既有商品與門市關聯驗證；商品／關聯停用仍可補登與整批更正，未知商品、未關聯與錯誤門市仍整批拒絕；庫存入帳、盤點涵蓋及更正規則照舊。新補貨仍排除停用品項。 |
| 草稿工具先抓新版，舊畫面繞過版本；暫存直接清除 | `draft-tools.js` 使用畫面版本；`ordering.js` 成功儲存後才更新工具版本，重載有版本不同的未儲存內容時保留輸入與舊版本；已確認儲存的本機內容可恢復最新伺服器版本，舊格式保守保留。封存／重建明確選儲存、放棄或取消，失敗不清暫存，409可另開視窗比對或確認放棄後重載。`orders.py` 已封存草稿也先核對版本。 |
| 履約401／403保留pending但鎖住整頁 | `fulfillment.js` 分開登入失效、權限拒絕、帳號變更與結果不明。權限拒絕保存原請求並只保護原案件，其他案件可操作，各操作有獨立儲存位置。重試手動觸發並重驗身份／門市；`modules/fulfillment/routes.py` 支援expected_actor_id，在伺服器寫入前拒絕換帳號。保存的舊請求依帳號隔離，既有儲存格式仍可讀。 |
| 管理刷新失敗未解除loading，寫入成功卻誤報失敗 | `management.js` 用finally結束目前載入，未載入時提供明確提示；`admin.html` 增加重試讀取按鈕。寫入及配送準備成功後刷新失敗，顯示已儲存及只需重試載入，不重送寫入。 |
| 首頁忽略封存導向的store_id | `app/__init__.py` 使用指定門市並核對權限，格式錯誤400；未知／停用／無權404，不洩漏草稿；未指定時沿用既有預設。 |
| 延遲出貨待查寫死60分鐘 | `fulfillment.py` 延遲待查採與手動待查相同的最新contact_minutes政策；原due／政策版本／round保存，重播不延長，重新排程後新異常採新政策。 |

規格澄清在 `spec.md` 第19節，維持原業務保護；README及CI加入新回歸入口。測試檔為 `tests/test_six_review.py`、`tests/recovery_ui.test.cjs`、`tests/browser_six_review.py`。

## 自動驗證

執行環境：Windows、Python 3.12虛擬環境、真實MySQL、Node、Playwright／Edge。環境檢查確認demo／test均在migration `a1410260003`。完整最後結果於交付時更新下表；開發期間曾失敗的測試已保留並修正原因，沒有刪除或跳過案例。

| 執行指令 | 最後結果 |
| --- | --- |
| `.\.venv\Scripts\python.exe scripts/check_environment.py` | demo／test均PASS |
| `$env:APP_ENV='test'; .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | 429 passed，235.80秒，無skip |
| `node --test tests/ordering_ui.test.cjs tests/recovery_ui.test.cjs` | 18 passed |
| 全部14個 `tests/browser*.py`（含 `browser_six_review.py` 的15項）以 `pytest -q … -p no:cacheprovider` 執行 | 95 passed，322.00秒，無skip；保留既有測試及斷言 |
| `.\.venv\Scripts\python.exe -m pytest -q -s tests/performance_integration.py tests/performance_open_history.py -p no:cacheprovider` | 2 passed，6.86秒；1000商品／14000歷史列計算1.211秒（門檻5秒），庫存狀態0.129秒／10 SELECT；歷史未結來源查詢0.010秒，數據一致 |
| `.\.venv\Scripts\python.exe -m compileall -q app tests scripts`；全部 `app/static/js/*.js` 的 `node --check`；`git diff --check` | PASS |
| `.\.venv\Scripts\python.exe -m flask --app wsgi db check` | No new upgrade operations detected |

新增驗證觀察實際HTTP、畫面輸入與儲存、資料庫銷量／庫存／草稿／待辦／出貨結果。Node只宣稱事件處理驗證，版面與瀏覽器行為由Playwright驗證。受控HTTP／網路錯誤用於復原路徑；新增案例的成功寫入均經真實B／C／D，不是模擬正式功能；既有模組開發瀏覽器測試另含受控供應者，不當作真實整合證據。

完整瀏覽器測試的PowerShell指令（不能直接將未展開的萬用字元交給pytest）：

```powershell
$env:APP_ENV='test'
$browserTestFiles=Get-ChildItem tests/browser*.py | Select-Object -ExpandProperty FullName
.\.venv\Scripts\python.exe -m pytest -q @browserTestFiles -p no:cacheprovider
```

本機無缺MySQL／瀏覽器而未執行的項目；不包含真人易用性、錄影或遠端GitHub Actions已通過的宣稱。執行期間一般沙箱帳號曾無法建立程序（Windows 1909），最後檢查及效能測試改用核准執行環境，仍使用同一隔離test DB。

## 組員人工核對

現在請組員核對合併版本。從此目錄依README啟動既有demo MySQL，先跑環境檢查，使用空MODULE_DEV。另開PowerShell：

```powershell
Set-Location C:\Users\user\Desktop\system2
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
$env:APP_ENV='demo'
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

帳號 `manager1`／`manager2`／`operator`／`admin`；密碼是既有種子建立時的DEMO_PASSWORD，不重設帳密或demo。先在同瀏覽器 `http://127.0.0.1:5000/api/auth/me` 核對帳號與門市id。測補貨／草稿需台北21:00–22:00，admin只能向前推進示範時鐘；若原資料不適合此情境，使用自己的獨立demo，不清理錄影資料。

1. 用admin在 `/admin` 停用本店一個已有銷售的商品或門市商品政策。manager在庫存資料頁驗證同SKU的歷史CSV及明確整批更正：應可匯入，歷史模式不扣庫存，新補貨不加入該SKU。混入未知SKU或其他門市碼：整批錯誤，不新增批次或部分銷量。
2. manager產生本輪建議並儲存草稿，兩視窗開同一 `/store/ordering?store_id=…&draft_id=…`。第二視窗改成6件並儲存；第一視窗改成42件及備註後按封存／帶回：先有儲存／放棄／取消選項，繼續應409，42件與備註仍保留；重載仍保留並提示伺服器有新版。另開視窗比對後，明確放棄並重載才以6件恢復。單視窗「儲存後繼續」應保留人工數量與備註；「放棄」使用原伺服器內容。重建前先重新計算，新草稿無舊確認。
3. operator在 `/headquarters/fulfillment` 開已接單訂單。開發者工具阻斷出貨請求：原內容與request_key保留、出現原內容重試；恢復網路重試只建一批。另視窗登入admin後回原畫面重試：顯示帳號已變更、拒絕送出、原請求留在operator的儲存範圍。回operator登入後可恢復。用店長待查／收貨測試移除原門市權限：重試提示無權，可切換其他授權門市工作，原請求仍保存。不要清空localStorage來解除結果不明。
4. admin開 `/admin`，開發者工具攔截catalog讀取使其失敗：有可見錯誤及「重試載入設定」，儲存會明確提示。恢復讀取重試後可編輯。再次僅攔截後續catalog讀取，改商品名稱並儲存：寫入200後畫面顯示「資料已儲存，畫面刷新失敗」，資料庫保留新名稱；重試載入看到新名稱，無需再儲存。
5. admin讓同店長可看兩間門市，在第二店封存草稿，返回 `/?store_id=第二店id`：標題與封存草稿均為第二店。改成無权門市應404，格式錯誤400，不能看到他店內容。
6. admin將本店商品contact_minutes設17。operator登記晚於承諾的物流ETA並填原因：承諾保留，待查期限為建立後17分鐘。等於承諾不新增延遲待查，晚一秒需要原因／待查。原識別重試不延長期限；查明後再異常建立下一round，採當時政策，舊due及逾期事實保留。時間顯示台北，跨午夜仍正確。

回報可直接貼：`我已核對六項修復，版本SHA：…；步驟…實際…預期…；錯誤文字／warning…；其餘步驟…通過。` 人類核對結果由組員確認後再記入驗收證據，不以AI自測代填。

## 資料與限制

沒有清理使用者資料，沒有schema／依賴變更。取消或失敗保留本機工作；瀏覽器自身清除儲存仍會失去尚未上傳的內容。權限被撤銷的原操作保存，必須由原身份恢復權限後處理；不能授權新身份代送。其他有權限案件的寫入不覆蓋該證據。真人操作時間、真人易用性評估與線上CI結果另記。

已完成全部本機自動檢查，依使用者授權提交本次檔案、直接合併main並同步遠端，不另開PR、不部署。最終提交、推送及合併後驗證結果見本次回覆。
