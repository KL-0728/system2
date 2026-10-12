# D 模組交接

## 2026-10-11：A 更新接入防護（不代填 D 進度）

main 已包含正式 B／C。MODULE_DEV=D 的測試注入只補缺少的插槽，不覆蓋正式 inventory_writer／orders。模組檢查頁逐一顯示實際服務來源；工廠訂單明示為獨立開發資料。D 的獨立案例仍可讀 fixture_only 訂單，正式 API／畫面不能使用這些訂單冒充 C 已送單。

- 同步 main 後執行 `python -m pytest tests/test_contracts.py tests/test_provider_integration.py`，再執行自己的履約測試。共用測試不能假設某提供者尚未實作。
- D 單元測試可明確 register_provider(test_only=True) 注入受控可失敗寫入；整合測試改用正式 B、同一 caller session。失敗必須讓最外層回滾履約與庫存，成功收貨重送只入帳一次。
- 舊替身異動沒有正式 B audit/result，不可當已入帳結果重放；B會回 SOURCE_RESULT_UNAVAILABLE，不以手動補假 audit 或再次加庫存解決。
- 已有防護測試涵蓋真實 B 的 caller 回滾／重試與拒絕舊替身来源；這是接入條件，**不是正式 D 收貨已驗證**。D交付後需用真實收貨入口重跑這些情境與兩連線 MySQL 併發。
- 提交PR前在獨立整合分支使用 main＋D 的精確head完整測試，含正式 C 訂單、同店／跨店、工廠／真實資料混合、分批收貨、版本失效與原請求重試。A不在審查中改寫D分支。

詳 [提供者整合修正](../provider-integration.md)。

人工操作與預期數字請依 [D 履約模組人工實測](../d-manual-testing.md)。

不清楚下一步時先看[組員操作入口](../team-start.md)：D使用MODULE_DEV=D及operator，店長收貨用manager1，依目前狀態取得啟動／實測／PR的指令；本模組進度仍以下表為準。

- 任務：統家履約、收貨及待辦；D01–D05 程式已在本機分支製作。2026-10-12 補上正式模式對 fixture_only 訂單的服務層阻擋，避免繞過列表／詳情隱藏後以品項 ID 異動。MySQL 自測已可執行，人工實測仍待成員操作。
- 發布：先核對 docs/parallel-ready.md 的實際基準與合約 v1；不可把 A03 支援當自己模組完成。
- 分支：feat/d-module；同分支連續 D01→D05，不等其他人成果合併。
- 自己的入口：app/modules/fulfillment/routes.py、services.py 的 install()；業務 models／services 依 agent.md。
- 開發模式：MODULE_DEV=D，外部替身 inventory_writer／orders；限獨立本機 demo DB，頁面明示來源。啟動、seed-module、check_module、合約測試與人工正常／錯誤步驟見 README「A03：B／C／D 各自開工」。
- 實測版本：本機分支 `feat/d-module` HEAD `c39497f`（D 模組已本機提交）；2026-10-13 專項加 Edge 瀏覽器測試 32 passed。提交前的全套 pytest 為 339 passed；後續修正的 ETA 時區序列化已含於 `c39497f`，目前尚未重跑全套。
- AI 模組自測：本機 D 專用 MySQL 8.4、`system2_d_demo`／`system2_d_test` 環境檢查兩項 PASS，migration `db check` 無差異。2026-10-13 修正出貨按鈕易混淆與差異備註預填問題後，test DB 全套 `pytest -q` **339 passed in 230.38s**；`pytest tests/browser_fulfillment.py tests/browser_fulfillment_full.py -q` **4 passed in 25.45s**，Edge 實際驗了 DEMO1 接單、原訂與補送出貨、收貨、損壞、報廢、重複阻擋，DEMO2 提案、爭議、待查、短收、多送品、待辦及跨店／角色權限；390px／1280px 無橫向溢出。瀏覽器測試使用隔離 test DB 外層交易，完成回滾，不改 demo。JS 語法及 `git diff --check` 通過。D MySQL root 管理密碼只在忽略的本機 `.env`，標準腳本重啟已驗證。
- 人工實測：尚未由組員確認完成。DEMO1 已接單 30、原出貨 5 並分次核對 2＋3（損壞 1），授權補送 1 尚未出貨；另有一批一般原訂出貨 1 待核對。飲料目前實體 25／不可售 1／可售 24。DEMO2 訂單仍 SUBMITTED、飲料 20／0／20。示範時鐘停於 2026-10-08 21:01 Asia/Taipei。完整續測數字見 d-manual-testing.md，勿重設或重新 seed。
- PR：尚未建立。
- 真實跨模組整合：待 A05；V 驗收待 A06。

| 階段 | 本次改動 | AI測試指令／結果／SHA | 人工步驟與結果 | 未完成／下一步 |
| --- | --- | --- | --- | --- |
| 01 | 已加入真實未結來源與履約摘要 | MySQL 合約測試已執行；4項純規則測試通過 | 未執行 | 仍需成員人工核對來源數字 |
| 02 | 已加入接受、拒絕、多批出貨、門市操作頁及初始接單待辦 | D 服務測試已執行；MySQL 交易測試通過 | 未執行 | 仍需瀏覽器實測 |
| 03 | 已加入分次收貨與真實 B 庫存介面呼叫 | D 收貨及正式 B 呼叫測試通過 | 未執行 | 兩連線 MySQL 併發與人工數字核對待驗 |
| 04 | 已加入提案、回覆、重申、取消與爭議出貨阻擋 | D 服務測試通過 | 未執行 | 兩連線 MySQL 併發待驗 |
| 05 | 已加入差異、補送、損壞品處置、雙方待辦與手機版樣式 | D 模組與提供者整合測試通過；Edge 4 項含正常／例外全流程通過 | 組員尚未確認 | 真實 C 送單接入待 A05；組員人工實測後才可交 Ready PR |

每階段依 agent.md 9.1 記錄，不只寫「通過」。模組末尾由人類實測後授權提交／推送／Ready PR；未完成實測可授權 Draft。提交僅列自己的實際檔案，不用 git add .，不自行合併 main。

可貼給 Codex：

> 我是D，A已宣布可以開始，請依agent.md確認A03基準、同步GitHub，在feat/d-module連續完成D01到D05；每階段自測並回報，最後給我完整實測指南與PR內容，不合併main。
