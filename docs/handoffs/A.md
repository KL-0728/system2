# A 任務紀錄

## 2026-10-08：A01 初始化檢查

- 成員：A；本次範圍：A01 至 A03。
- 儲存庫：https://github.com/KL-0728/system2.git
- 本機起始狀態：尚無 .git；既有 agent.md、spec.md、AGENTS.md 與 .github/pull_request_template.md 全數保留。
- 遠端檢查：`git ls-remote --symref https://github.com/KL-0728/system2.git HEAD refs/heads/main` 與完整 `git ls-remote` 均 exit 0，沒有 refs。遠端為空，尚無 main SHA 或可同步基準。
- Git 提交身份已設定；未新增或修改身份設定。
- 新增 .gitignore，排除環境秘密、Python 快取、本機資料庫與備份。
- 尚未提交、推送、開 PR 或合併。分支保護未設定，也未透過 GitHub 管理 API 驗證。
- A01 尚未完成；A02／A03 尚未開始。依 agent.md 第 6.1 節，須先完成 A01 main 初始化才可進行 A02。

## A01 人工核對

1. `git remote -v` → origin 的 fetch／push URL 均應為指定儲存庫。
2. `git status --short --branch` → 首次提交前應顯示 main 尚無提交，既有文件及新增文件待加入。
3. `git check-ignore .env .venv/test instance/demo.db backup.sql` → 四個路徑均被忽略；`git check-ignore .env.example` → 不應被忽略。
4. 授權首次提交與推送後，核對遠端 main 與本機 HEAD SHA 相同；成功前不可通知組員開始製作。

## 待授權及後續

agent.md 第 8 節要求提交、推送及合併有明確授權。A01 首次 main 提交／推送、A02／A03 任務分支提交／推送／PR 待確認。A 自己的 PR 依第 5.2 節由另一位組員複核後，再由 A 合併。

A03 未發布前，B／C／D 請勿開始模組製作。A02／A03 的 Flask、MySQL、合約及獨立模組測試尚未執行；目前沒有產品驗收通過證據。
