# A 任務紀錄

## 2026-10-08 組員操作與回報指引再檢討

- 成員A；製作基準main／origin/main為1744fbd，程式發布標記a03-parallel-v2。本次文件改善從docs/team-workflow-guide製作，A已明確授權用繁體中文提交並推送main、確認GitHub CI；不移動已發布標記。
- 新增docs/team-start.md：區分首次安裝／日常啟動、聊天指令／終端機命令，列出狀態對應下一句、合成示範帳密、環境變數優先順序、模組404判讀，以及先查身份再取門市id的雙向跨店步驟。README與三人交接檔提供入口，沒有變更B／C／D模組進度。
- .env.example改為團隊約定的合成示範密碼，私人.env、DB憑證與SECRET_KEY不納版控。既有帳號不自動改密碼，指引明寫保留資料的處理方式。
- agent.md要求每次說明當下行動、具體操作、預期結果與下一句；GitHub提交訊息、PR及發布備註用繁體中文，不改寫已推送的英文提交歷史。
- 本次內容核對：修改文件的本機連結目標存在、Git差異空白檢查通過。Flask HTTP客戶端確認manager1／manager2身份，讀本店均200、他店均404；C頁200、B頁404 NOT_FOUND。未操作瀏覽器；沒有業務程式變更，未為文件修訂重跑整套pytest，已發布版本36項通過證據見前節。
- 發布核對：提交後確認origin/main與本機HEAD一致、工作目錄乾淨，並核對該提交的GitHub mysql-tests結果；以實際Git與CI紀錄為準，不預填通過。組員同步main即可取得新操作指引，程式基準仍為a03-parallel-v2。

## 2026-10-08 本機啟動修正版發布

- A已授權提交並直接推送main、更新發布基準與組員指引；本次不開PR。發布標記a03-parallel-v2於main提交的GitHub CI成功後建立，精確SHA由標記解析，v1保留。
- 發布前：scripts/check_environment.py兩個DB皆PASS；pytest 36 passed in 11.61s；啟動腳本已運行時不重複啟動路徑通過。先前四個共用示範帳號HTTP登入皆200。冷啟動腳本未以停止使用中的DB重驗，保留此限制。
- A回報登入成功與跨店檢查完成；未逐筆提供最後的跨店回應，不擴大為完整產品驗收。A04–A07及真實跨模組整合仍未完成。
- docs/parallel-ready.md頂端更新v2基準及組員取得、環境檢查、開工指令。下方各節「未提交／未推送」為修復過程的歷史紀錄，本節及實際Git狀態優先。

## 本機示範帳號共用密碼

- 依A要求，四個本機示範帳號manager1／manager2／operator／admin統一使用指定的示範密碼，並同步未追蹤的.env；版控文件不記錄密碼值。保留門市、商品、訂單及其他既有資料。
- seed-demo的示範密碼最低長度由12調整為8，使後續重建可接受指定值；README同步說明僅供本機示範共用，以及修改.env不會自動更新既有帳號。
- 以Flask HTTP測試客戶端逐一登入四個帳號，均為200且/api/auth/me身份正確。修改仍在fix/a03-local-startup，未提交／推送。

## 本機啟動修復後的核對與共同指引補強

- 使用者回報：`36 passed, 1 warning in 11.57s`，先前26個DB連線錯誤已解除；尚未提供warning內文，不推定原因或宣稱無害。
- AI本次核對：`scripts/check_environment.py`的demo／test皆PASS；`python -m pytest -q`為`36 passed in 11.68s`，本次未重現warning。未執行瀏覽器人工操作。
- 共用指引：README補上所有成員每次重新開工的DB檢查、測試後切回demo，以及A03登入／模組頁／跨店隔離的具體人工核對步驟。agent.md第9節要求先確認實際DB連線，第9.1節明定結束回覆直接附改動、測試、實測方法與下一步，文件連結僅補充；錯誤回報保留warning內文。
- 本次未改產品規格或業務功能。版本為e39f1df加fix/a03-local-startup分支未提交修改；尚未提交、推送或開PR，其他組員仍需取得發布後的修正才會看到新指引。A03發布標籤不變。
- 下一步：A依README「A03 自動測試通過後的人工核對」操作並記錄結果；若仍有warning，回報warnings summary全文（遮蔽憑證）。

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

## A03 候選版製作／自測

- 開發前 fetch／pull --ff-only 成功；main 基準 0b3e356，目錄乾淨。
- 36張共用表、FK／唯一約束及 nullable 輸出、追加式稽核／異動／快照守衛；全套 DTO／Protocol、服務注入、三個成員路由／installer。
- 可失敗庫存替身、未結風險／完整性／run替身、C持久化run工廠與D正式表訂單工廠；僅test／明示模組開發模式。D測試訂單 fixture_only=True，未將 C 送單替換成假成功。
- 新建 .venv-clean 安裝鎖定依賴，空test DB從零upgrade成功；migration 884e7a53a8c8，db check無差異；36項MySQL自測通過。
- 獨立 B／C／D check_module 各通過；seed-module C／D後有可用實體FK資料。示範基礎：兩店、10品項、各14日歷史、現貨20；受控run飲料建議30。
- 真實MySQL兩連線鎖測試、受控寫入回滾／冪等、null、重要風險、模式拒絕通過。登入限流實測5次401、第6次429。
- 重建發現 MySQL downgrade 的 FK索引限制；未改已發布 A02 revision，改以驗空test schema明確重建後驗完整升級鏈。資料回退不在基準保證。
- 修正 PowerShell 管線造成 acceptance.md 中文損壞，改由Unicode安全寫入；未改產品規格。
- 人工瀏覽器／手機尚未執行，完整步驟見 README；V表維持尚未驗收。
- 下一步：最終受影響自測、核對差異、main提交／推送、確認CI與保護、發布基準及標記。

## A01–A03 發布結果

- A01 1c56c7f、A02 0b3e356、A03程式基準 ef653c73e2b44cfe4a5988a4cc81723e9406e8a0，均已實際推main。本次不開PR、不部署。
- A02 GitHub CI success：https://github.com/KL-0728/system2/actions/runs/37663516757 。A03 MySQL8.4 migration／pytest／schema check 全部成功：https://github.com/KL-0728/system2/actions/runs/37666023805 。發布公告提交另追加MODULE_DEV測試隔離（28項重驗通過）及文件整理，發布標記a03-parallel-v1於最後CI核對後建立。
- 最後原訂量／確認快照守衛重驗：2 passed。main保護設定並讀回：PR1人審核、stale review失效、mysql-tests strict必要檢查、對話解決、禁止force push與刪除；管理者豁免，僅A合併仍為團隊規則。
- 本機 .env／instance／兩套venv均未追蹤，工作資料保留。獨立MySQL3307仍在執行，A可按README啟動Flask實測；既有MySQL96未更動。先前詢問的既有DB連線不再需要。
- 完整發布狀態／標記解析方式見parallel-ready。各成員的下一步／實際命令／人工預期結果見README與各自交接檔，V表未誤標產品通過。
- 現在：請A依README核對登入、跨店與三模組基礎頁，將發布指引交B／C／D；三人可各自開始01→05。A04–A07不在本次範圍。

## A03 本機實測失敗修復（2026-10-08）

- 使用者回報：10 passed、2 warnings、26 errors。重新核對 .env，demo與test均指向127.0.0.1:3307；TCP實測ConnectionRefusedError。既有MySQL96／3306不是這份checkout使用的資料庫。
- 同步：fetch與pull --ff-only成功，HEAD／origin/main均e39f1df，工作目錄乾淨；修復分支fix/a03-local-startup。
- 保留原instance/mysql-data與.env，只啟動既有獨立MySQL，不初始化、不清資料、不改既有MySQL服務。
- 修改：README把資料庫啟動／環境檢查放在pytest前；新增scripts/start_a_mysql.ps1（只啟動既有A資料目錄、隱藏視窗、等待3307可用、已啟動則不重啟）與scripts/check_environment.py（唯讀檢查demo／test連線及migration head，不輸出憑證）。產品程式／規格／已發布migration未改動。
- 實測：兩個DB檢查PASS，head 884e7a53a8c8；pytest -q → **36 passed in 11.70s**。check_module.py B／C／D全部通過。另用未開啟的本機59999測check_environment錯誤路徑，回MySQL2003及exit1，未操作真實資料。啟動腳本的「已有3307不重啟」路徑已驗證；本次冷啟動是以README原始Start-Process參數執行成功，未為測腳本再停止使用中的資料庫。
- 測試版本：e39f1df加上述未提交修復。本次尚未提交／推送／開PR，不移動a03-parallel-v1。
- 使用者重測：先在自己的PowerShell執行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_a_mysql.ps1`；再執行 `.\.venv\Scripts\python scripts/check_environment.py`，兩行PASS後執行 `.\.venv\Scripts\python -m pytest -q`，預期36 passed。重開電腦後先做同樣檢查，不重新複製.env或seed-demo。
- 人工瀏覽器／手機尚未實測。下一步請A重跑以上三步；若仍失敗，提供第一個FAIL／ERROR的錯誤文字與指令（遮蔽憑證），不只測試統計摘要。
