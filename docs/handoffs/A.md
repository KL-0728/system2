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

A03 未發布前，B／C／D 請勿開始模組製作。目前沒有產品驗收通過證據。

## 本次授權與 A01 結果

使用者明確授權：「因為是前置作業 所以都直接main推上去就好了 不用開PR」。本次 A01–A03 因此直接 main 提交／推送；不改 B／C／D 分支規則。A01 首次 main 為 1c56c7f，推送並 fetch／pull --ff-only 驗證成功，origin/main 與 HEAD 一致。既有規格的 Markdown 雙空白換行保留，未改規格。main 保護尚未設定；GitHub 管理 API／gh CLI 不可用，不能宣稱已受平台保護。

## A02 製作／自測

- 基準 1c56c7f，main；本節測試含 A02 未提交修改，提交後可用 Git 任務訊息定位版本。
- Flask factory、密碼雜湊、登入／登出／CSRF、速率限制、跨店／角色／停用帳號保護、共用版型、UTC／台北時鐘、版本鎖、交易及稽核介面。
- 新增獨立 demo／test 設定防誤用、種子、安全 demo 重設、版本化政策與 identity／catalog 模型；建立 requirements、README、CI、tasks、acceptance、contracts。
- 本機 MySQL96 既有服務拒絕空密碼，未修改。另於忽略的 instance/mysql-data 初始化獨立 MySQL 9.6.0／3307，僅綁 127.0.0.1，建立 system2_a_demo／system2_a_test 與本機隨機密碼，寫入未追蹤 .env。未輸出憑證。
- 實際執行：compileall；flask db migrate／upgrade（demo、test）；seed-demo；pytest -q → **6 passed**；flask db check → 無結構差異。
- 發現並修正：Windows 缺 tzdata；登入 session 重設後 CSRF token 快取未清；測試種子須釋放內層 savepoint 以保留外層隔離。
- migration head：2ce34638ca9a。CI 定義已建立，遠端 Actions 結果尚未讀取。
- 人工實測：尚未執行；步驟見 README「A02 實測」。管理畫面留 A04；完整 V20／V44 與併發驗收留 A06，不以基礎單元測試宣稱通過。
- 現在：AI 繼續 A03，A 暫無需操作。
