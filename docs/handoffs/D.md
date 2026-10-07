# D 模組交接

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
