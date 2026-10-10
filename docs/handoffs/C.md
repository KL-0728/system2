# C 模組交接

不清楚下一步時先看[組員操作入口](../team-start.md)：C使用MODULE_DEV=C及manager1，依目前狀態取得啟動／實測／PR的指令；本模組進度仍以下表為準。

- 任務：店長訂購及可靠送單；C01–C05 已完成本機實作、AI 自測及 C 組員人工實測。
- 發布：先核對 docs/parallel-ready.md 的實際基準與合約 v1；不可把 A03 支援當自己模組完成。
- 分支：feat/c-module；同分支連續 C01→C05，不等其他人成果合併。
- 自己的入口：app/modules/ordering/routes.py、services.py 的 install()；業務 models／services 依 agent.md。
- 開發模式：MODULE_DEV=C，外部替身 runs／integrity／open_orders／fulfillment；限獨立本機 demo DB，頁面明示來源。啟動、seed-module、check_module、合約測試與人工正常／錯誤步驟見 README「A03：B／C／D 各自開工」。
- 實測版本：`feat/c-module`，基準 `1be4c30`；C 模組實作提交 `99dded0`。
- AI 模組自測：`python -m pytest -q` 為 44 passed；C 專項 `tests/test_confirmation.py tests/test_submission.py` 為 8 passed；Python／Jinja／JavaScript 語法及 `check_module.py C` 通過。實際 Flask HTTP 檢查登入、首頁及工作台200，未啟用B模組404。測試 DB 為 `system2_c_test`，demo 為 `system2_c_demo`；未以瀏覽器宣稱手機人工實測。
- 人工實測：C 組員於 2026-10-10 回報已依本指南實測通過；未提供瀏覽器版本等額外細節，不代填未回報資料。
- PR：[Ready PR #1](https://github.com/KL-0728/system2/pull/1)，交由 A 審核；C 不合併 main。
- 真實跨模組整合：待 A05；V 驗收待 A06。

| 階段 | 本次改動 | AI測試指令／結果／SHA | 人工步驟與結果 | 未完成／下一步 |
| --- | --- | --- | --- | --- |
| 01 | 草稿建立／版本修改、來源唯一性、不可變原訂量及正式 orders provider | C 專項測試含首次說明、版本、跨店與原訂量；通過 | C 回報依指南通過 | 交 A 審核 |
| 02 | 首次說明、三階段工作台、件／箱、理由、計算明細、桌面／手機版型 | Jinja解析、JS語法、HTTP頁面測試通過 | C 回報依指南通過 | 共用首頁入口交 A 整合 |
| 03 | 五分鐘token、截止／版本／風險重驗、原子送單、冪等重試與結果查詢 | 正常送單、過期、版本衝突、同key重試／衝突測試通過 | C 回報依指南通過 | 交 A 審核 |
| 04 | 直接訂購null、重要例外合併確認、待處理篩選、D供貨摘要／時間軸／待辦入口 | 1000件特殊情境、缺確認拒絕與完整送單測試通過 | C 回報依指南通過 | 真實 B／D 操作待 A05 整合 |
| 05 | 訂單列表／明細、手機收尾、網路未知結果復原、影片腳本與交接 | 全套44 passed；影片腳本位於demo/video-script-zh.md | C 回報依指南通過 | Ready PR 交 A 審核 |

## C 模組人工實測指南

### 準備

1. 分支為 `feat/c-module`；保留未提交修改。確認 `scripts/check_environment.py` 的 demo／test 兩行均 PASS。
2. 在專案根目錄啟動：`$env:APP_ENV='demo'`、`$env:MODULE_DEV='C'`，再執行 `python -m flask --app wsgi run --host 127.0.0.1 --port 5000`。
3. 一般視窗以 `manager1` 登入；密碼來源為本機 `.env` 的 `DEMO_PASSWORD`，不要回報密碼。先到 `/api/auth/me` 確認 username 及 DEMO1 門市 id。

### 正常路徑

1. 開 `/store/ordering?store_id=<DEMO1門市id>`；首次顯示完整說明，未勾選時按確認應顯示錯誤，勾選後才進工作台。
2. 確認三階段、10商品、件／箱、待接單與已承諾分開；展開飲料的「為什麼訂這個數量」，應看見預估、目標、安全庫存及取整。
3. 維持30件建議，按「儲存並核對提醒」；正常案例不應出現逐品項確認，只需一次全單確認。
4. 未勾全單確認直接送出應拒絕；勾選後送出應取得訂單 ID／編號。到 `/store/orders?store_id=<id>` 應只出現一張，明細原訂量保持30。

### 重要例外與錯誤

1. 新草稿把雨衣改1000件，選在地需求，理由至少10字並填日期／需求量／交付安排；預覽應顯示大量、容量及特殊需求，且「只看待處理」數量正確。
2. 缺品項確認或處理方式時送出應拒絕；全部處理並勾全單確認後才成功。特殊直接訂購的 `mu／建議量=null` 目前由 `test_direct_special_order_keeps_null_model_and_requires_item_ack` 受控情境驗證；一般 demo 的正常 run 不冒充直接訂購案例，真實 B direct run 待 A05 接入後再做人工作業。
3. 修改草稿後使用舊版本、等待token超過五分鐘，或資料版本改變，應回409並要求重新預覽，不丟失畫面輸入。
4. 模擬送出後瀏覽器斷線時，應顯示「尚未確認送出結果」；按查詢結果使用原key，不另建新單。同一訂單在列表仍只有一張。
5. manager1嘗試 DEMO2 store_id 應404。一般與無痕視窗的完整雙向跨店步驟依 `docs/team-start.md` 第5節執行。

### 手機與交接判斷

1. 瀏覽器寬度設約390px，完成正常補貨及1000件雨衣流程；商品名稱、單位、提醒與送出按鈕須可見，不能依賴橫向捲動。
2. 訂單明細應分開顯示原始訂購、供貨狀態、變更時間軸與待辦；C開發模式的D內容標示受控來源，不能當真實D整合通過。
3. 記錄每一步實際／預期、錯誤文字、瀏覽器與約略寬度；本次由 C 組員回報已依指南通過。

每階段依 agent.md 9.1 記錄，不只寫「通過」。模組末尾由人類實測後授權提交／推送／Ready PR；未完成實測可授權 Draft。提交僅列自己的實際檔案，不用 git add .，不自行合併 main。

可貼給 Codex：

> 我是C，A已宣布可以開始，請依agent.md確認A03基準、同步GitHub，在feat/c-module連續完成C01到C05；每階段自測並回報，最後給我完整實測指南與PR內容，不合併main。
