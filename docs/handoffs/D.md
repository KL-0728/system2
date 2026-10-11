# D 模組交接

## 2026-10-11：A 更新接入防護（不代填 D 進度）

main 已包含正式 B／C。MODULE_DEV=D 的測試注入只補缺少的插槽，不覆蓋正式 inventory_writer／orders。模組檢查頁逐一顯示實際服務來源；工廠訂單明示為獨立開發資料。D 的獨立案例仍可讀 fixture_only 訂單，正式 API／畫面不能使用這些訂單冒充 C 已送單。

- 同步 main 後執行 `python -m pytest tests/test_contracts.py tests/test_provider_integration.py`，再執行自己的履約測試。共用測試不能假設某提供者尚未實作。
- D 單元測試可明確 register_provider(test_only=True) 注入受控可失敗寫入；整合測試改用正式 B、同一 caller session。失敗必須讓最外層回滾履約與庫存，成功收貨重送只入帳一次。
- 舊替身異動沒有正式 B audit/result，不可當已入帳結果重放；B會回 SOURCE_RESULT_UNAVAILABLE，不以手動補假 audit 或再次加庫存解決。
- 已有防護測試涵蓋真實 B 的 caller 回滾／重試與拒絕舊替身来源；這是接入條件，**不是正式 D 收貨已驗證**。D交付後需用真實收貨入口重跑這些情境與兩連線 MySQL 併發。
- 提交PR前在獨立整合分支使用 main＋D 的精確head完整測試，含正式 C 訂單、同店／跨店、工廠／真實資料混合、分批收貨、版本失效與原請求重試。A不在審查中改寫D分支。

詳 [提供者整合修正](../provider-integration.md)。

不清楚下一步時先看[組員操作入口](../team-start.md)：D使用MODULE_DEV=D及operator，店長收貨用manager1，依目前狀態取得啟動／實測／PR的指令；本模組進度仍以下表為準。

- 任務：統家履約、收貨及待辦；目前 D01–D05 尚未開始。
- 發布：先核對 docs/parallel-ready.md 的實際基準與合約 v1；不可把 A03 支援當自己模組完成。
- 分支：feat/d-module；同分支連續 D01→D05，不等其他人成果合併。
- 自己的入口：app/modules/fulfillment/routes.py、services.py 的 install()；業務 models／services 依 agent.md。
- 開發模式：MODULE_DEV=D，外部替身 inventory_writer／orders；限獨立本機 demo DB，頁面明示來源。啟動、seed-module、check_module、合約測試與人工正常／錯誤步驟見 README「A03：B／C／D 各自開工」。
- 實測版本：尚無 D 模組提交。
- AI 模組自測：未執行；A03 共用合約證據見 parallel-ready，不代填本模組通過。
- 人工實測：未執行。
- PR：尚未建立。
- 真實跨模組整合：待 A05；V 驗收待 A06。

| 階段 | 本次改動 | AI測試指令／結果／SHA | 人工步驟與結果 | 未完成／下一步 |
| --- | --- | --- | --- | --- |
| 01 | 未開始 | 未執行 | 未執行 | 確認發布基準後開工 |
| 02 | 未開始 | 未執行 | 未執行 | 本分支01自測後繼續 |
| 03 | 未開始 | 未執行 | 未執行 | 本分支02自測後繼續 |
| 04 | 未開始 | 未執行 | 未執行 | 本分支03自測後繼續 |
| 05 | 未開始 | 未執行 | 未執行 | 完整人工指南及交接 |

每階段依 agent.md 9.1 記錄，不只寫「通過」。模組末尾由人類實測後授權提交／推送／Ready PR；未完成實測可授權 Draft。提交僅列自己的實際檔案，不用 git add .，不自行合併 main。

可貼給 Codex：

> 我是D，A已宣布可以開始，請依agent.md確認A03基準、同步GitHub，在feat/d-module連續完成D01到D05；每階段自測並回報，最後給我完整實測指南與PR內容，不合併main。
