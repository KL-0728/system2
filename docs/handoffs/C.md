# C 模組交接

不清楚下一步時先看[組員操作入口](../team-start.md)：C使用MODULE_DEV=C及manager1，依目前狀態取得啟動／實測／PR的指令；本模組進度仍以下表為準。

- 任務：店長訂購及可靠送單；目前 C01–C05 尚未開始。
- 發布：先核對 docs/parallel-ready.md 的實際基準與合約 v1；不可把 A03 支援當自己模組完成。
- 分支：feat/c-module；同分支連續 C01→C05，不等其他人成果合併。
- 自己的入口：app/modules/ordering/routes.py、services.py 的 install()；業務 models／services 依 agent.md。
- 開發模式：MODULE_DEV=C，外部替身 runs／integrity／open_orders／fulfillment；限獨立本機 demo DB，頁面明示來源。啟動、seed-module、check_module、合約測試與人工正常／錯誤步驟見 README「A03：B／C／D 各自開工」。
- 實測版本：尚無 C 模組提交。
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

> 我是C，A已宣布可以開始，請依agent.md確認A03基準、同步GitHub，在feat/c-module連續完成C01到C05；每階段自測並回報，最後給我完整實測指南與PR內容，不合併main。
