# 任務總覽

最新狀態（2026-10-13）：A已授權納入全部既有成果，完成全系統檢查、修正、提交及直接推main。發布流程與最後驗證結果見[檢查報告](project-review-2026-10-13.md)；A04管理及A05真實整合已具備可運行程式，A06的三位真人驗收和A07影片仍須團隊完成。下方未提交描述保留作前一輪歷史。

2026-10-13：D PR #6已合併main，來源head dd39baf、合併b45cccb。A收尾分支chore/a-project-completion以此為基準，管理設定與真實B／C／D閉環已加入；成果仍為未提交本機修改。實測見[a-completion-testing.md](a-completion-testing.md)，自測證據與限制見[a-completion-report.md](a-completion-report.md)。歷史交接中的「尚未提交」描述各次工作當時狀態。

規則以 agent.md 第6節為準。本次 A01–A03 經使用者授權直接推 main，不開 PR，不延伸到成員模組。

| 任務 | 狀態 | 證據／下一步 |
| --- | --- | --- |
| A01 | 已完成 | 1c56c7f；main保護已設定及讀回，管理者例外見parallel-ready |
| A02 | 已提交推送 main | 0b3e356；6項 MySQL 基礎測試；GitHub CI success |
| A03 | 已發布共用基礎 | 原程式基準ef653c7；目前啟動基礎標記a03-parallel-v2；見parallel-ready.md |
| B01–B05 | PR #3已合併main | B head 952d99f；合併527ba2e；模組測試與人類實測狀態見handoffs/B.md |
| C01–C05 | PR #1已合併main | 合併ab704d9；A介面補修已由PR #2合併f2d5f67，來源修正已由PR #4合併bd906a0；見handoffs/C.md |
| D01–D05 | PR #6已合併main | dd39baf → b45cccb；D人工實測歷史紀錄保留，A另驗真實C送單與B收貨 |
| A04 | 管理功能已本機實作 | 商品／門市／帳號／政策、示範時鐘、稽核與安全重設指引；待成員複核 |
| A05 | 真實閉環已本機自測 | 無替身B→C→D→B、回滾及MySQL併發；本次整合修改尚未合併main，合併後仍須重驗 |
| A06 | 自動化驗證與效能已執行；人工驗收未完成 | 逐項證據見收尾報告；三位真人逐人計時、完整V確認不能代填 |
| A07 | 腳本及交付指南已備妥；影片未完成 | 腳本已對齊真實服務；待團隊錄影／剪輯、上傳YouTube及繳交網址 |
