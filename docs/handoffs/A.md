# A 任務紀錄

## 補修分支上傳（2026-10-10）

- 使用者已授權提交／推送這批累積補修；範圍為 `fix/a-c-order-validation`，不合併main、不修改C分支。提交前fetch成功，HEAD／origin/main為ab704d9，main包含於修正分支歷史中。
- 上傳前重新執行MySQL完整pytest：79 passed in47.60s；Node事件測試2 passed。Edge前一輪11個案例均已驗證通過，本次只補文件，未改測試後的功能程式。
- 新增 [共用配色與排版指引](../ui-guidelines.md)，並在team-start連結；組員繼承base.html與app.css，模組特殊樣式独立維護。合併main、組員同步後才取得此版，不把分支推送視為全員已更新。
- 僅提交明確的程式、測試與文件；本機.review審查副本、.env、instance資料、瀏覽器截圖與venv保留在本機。
- 下一步：A從GitHub比較修正分支與main，依人工指南核對後請相關成員審查；主線合併另依A的授權安排。既有紀錄中的「未提交／未推送」描述各次補修當時狀態。

## 配色選項④：淺灰＋靛紫

- 使用者選④，已修改app.css／ordering.css：主色#6250A5、背景#F5F4FA、白卡片、深紫header#29233F；導航、階段、表單、工具列、確認視窗及次要文字統一配色。錯誤紅、警示琥珀、成功／承諾綠保留。
- 本次只改CSS，不影響API、資料表或業務規則。既有fix/a-c-order-validation（ab704d9加未提交修改），未提交推送。
- 環境檢查demo／test PASS。真實Edge桌面1440與手機390兩項通過（7.17s），核對無橫向溢出、欄位對齊、草稿恢复與送單，已查看兩張截圖；git diff --check通過。本次配色不重跑無關後端測試。
- A現在瀏覽器Ctrl+F5，核對首頁／補貨／預覽按鈕為靛紫、背景淺灰紫、警示仍琥珀。若仍是綠色先確認強制重新整理；暫不提交推送。

## 恢復建議量的自動說明不再混入排除

- 原因：恢復按鈕自動寫入「依本輪系統建議恢復訂購數量」，排除確認原樣預填，造成相反動作的說明混用。
- 修正：恢復時保留既有自填說明，僅空白時補恢復記錄；開排除視窗時不沿用這句已知自動文字，包括已儲存的舊草稿。取消仍保留原草稿，確認才設skip與新的補充說明。未變更已送訂單或demo資料。
- 自測：Node2項、JS語法通過；真實Edge針對排除與手機2項通過（8.52s），包含恢復→儲存→重載→排除、取消、確認清除自動文字及自填說明保留。本次前端局部修改，不重跑無關後端測試；先前完整79／瀏覽器8項為前次版本證據。
- 本機分支fix/a-c-order-validation，基準ab704d9加未提交修改；未提交推送。A現在Ctrl+F5，重開本次不訂確認視窗，核對補充欄不含恢復用語，再自行確認／儲存。

## 排除確認、登出與桌面重新排版

- 本次仍在fix/a-c-order-validation，HEAD及fetch後origin/main皆ab704d9；保留前次未提交成果，未提交推送、不改C分支。
- 工作台與預覽排除共用native dialog：預設焦點在取消，取消／Esc保留原值；確認才設0與skip，原說明預填，可選填補充。依spec6.4，skip即有效原因，不另外強迫文字。
- 預覽列本次不訂清單與原因；訂單決策明細顯示reason_code對應中文，修正skip無補充文字誤顯示一般未調整。
- 新增共用登出表單與/logout POST，保持原/api/auth/logout JSON合約。CSRF拒絕與登出撤銷session測試通過。
- 電腦五欄數量資料＋整列原因／說明；調整全站header、配色、階段導航、間距、輸入大小、單位、數字對齊。儲存／預覽工具列移到商品上方並隨捲動保留，避免底部浮動列遮住理由輸入。既有手機流程保留。實際Edge測1440／1280／1024／768／390px，檢查水平溢出與桌面欄位／原因輸入對齊、排除取消／Esc／確認及登出。
- 完整MySQL **79 passed in39.36s**，Node事件 **2 passed**，JS語法與空白檢查通過。最後工具列移位後真實Edge **8 passed in27.84s**。截圖在忽略的instance/browser-check，已查看電腦商品卡與确认視窗。資料表、migration與provider DTO不變；B／D真實整合仍未完成。
- 現在請A依[最新重測五步](../a-manual-testing.md)核對外觀及操作，暫不提交推送。

## A人工實測回饋補修：非法數量與排除入口

- 唯讀檢查manager1草稿9：雨衣120、理由3個非空白字元，阻擋為`IMPORTANT_REASON_REQUIRED`；没有更動demo草稿。
- 依spec保留非法輸入供修正，不自動還原。工作台新增「恢復建議量」與「本次不訂」按鈕；後者設0、原因skip，未直接送單。直接訂購無建議時禁用恢復按鈕。
- 預覽阻擋訊息加入商品名稱及修正方法，且顯示在該商品旁。錯誤details保留product_id／codes，增加name／messages，不改資料表、DTO或C分支。
- 新增短理由回歸測試；真實Edge手機實測短理由定位、恢復30、直接排除0、重新預覽270與完整1000件送單通過。Node2項與JS語法通過。現在請A重新啟動Flask、Ctrl+F5，只重測雨衣理由／恢復量／本次不訂；未提交推送。
- 本次補修後完整MySQL回歸：**78 passed in39.11s**，前次77項證據保留於歷史段落。

## 2026-10-10 後續優化與實測交接（目前版本）

- A補修分支`fix/a-c-order-validation`，HEAD／origin/main基準`ab704d9`加未提交修改；本次沒有提交、推送、PR或合併，不改C分支。
- 已修草稿誤選D工廠run、撤權仍讀草稿、開放／截止邊界、登入格式錯誤、頁面重載與未知送單恢復、雙連線同鍵重送404。完成首頁入口、明確預覽、決策明細、20筆分頁、policy批次查詢與桌面／平板／手機CSS。
- MySQL9.6／3307完整pytest **77 passed in36.19s**；含3項獨立連線併發驗證。Node24事件測試 **2 passed**，已加CI（遠端尚未推送執行）。JavaScript語法及db check通過，migration head仍`884e7a53a8c8`。
- 真實Edge **5 passed in15.48s**：1440／768／390px，一般單、恢復草稿、手機排除與1000件特殊需求、後端成功回應丟失後重載找到原單。測試限定test DB，沒有清理或送單到demo。完整操作看[人工實測指南](../a-manual-testing.md)。
- 介面與資料表不變；新增分頁metadata及內部snapshot政策參數。B／D真實履約、庫存、首頁期限待辦、1000商品效能及影片仍待A05–A07驗證。
- 對應V04–V11、V20、V22、V31、V40部分模組證據，不宣稱完整V通過。現在請A人工實測指南步驟1–12並回報；C複核變更，暫不提交推送。

以下保留此前階段紀錄。

## 2026-10-10 C已合併後的A補修與全專案檢查

- 授權：A要求獨立分支修正C三個已重現問題並自測，另從不同角色檢查全專案；本次不提交、推送或合併。
- fetch及pull --ff-only成功；main／origin/main與本次HEAD基準為ab704d9，包含PR #1。從此建立fix/a-c-order-validation；保留前輪.review未追蹤審查資料，未修改C分支。
- 修正：排除品項返回草稿改0、後端拒絕矛盾排除；0量問題商品不阻擋有效品項；特殊需求結構欄位驗證；空白數量前端阻止。
- MySQL全套63 passed in 33.03s；Node事件測試2 passed；schema check無差異；語法與空白檢查通過。本機demo唯讀HTTP正常與跨店拒絕通過。桌面／手機瀏覽器未實測、真實B／D未整合。
- 另外4個隔離探測重現未修問題：20:59與22:00預覽放行、非物件登入JSON回500、門市停用後草稿仍可讀。探測不列入63項已通過測試；詳細優先順序、責任與限制見[本輪檢查](../project-review-2026-10-10.md)。
- 新增錯誤碼與C檔案變更由A本次補修，交C核對；不修改共用DTO／規格／migration。狀態為未提交修改，C原Ready交付紀錄不代寫成此版驗收。
- 現在請A依檢查文件的5010啟動、8步人工流程實測並回報。先保留本機，不提交推送；A05／A06仍待真實B／D交付整合。

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
## 文字對齊與草稿操作補修（2026-10-10）

- 延續A整合分支 `fix/a-c-order-validation`，HEAD／origin/main基準 `ab704d9`；保留先前未提交工作，不改C分支、不提交／推送／合併。
- 使用者截圖中的數量下方操作文字：去除按鈕左右內距，統一說明／狀態／操作字級及行高，保留點擊高度。預覽與排除視窗把數量拆成兩欄，來源可換行、checkbox文字独立換行、確認按鈕不拆字。
- 補修儲存途中商品欄位仍可編輯，以及瀏覽器舊內容蓋過其他分頁新草稿：儲存暫停欄位，完成／失敗還原；本機快取紀錄草稿版本，版本不同恢復伺服器內容並提醒。
- 實測：Edge11個案例通過（首輪10 passed／1測試腳本失敗；修正重複首次說明步驟後該項1 passed），Node2 passed、JavaScript語法通過；隔離test資料，demo未重設。先前後端完整79 passed，本次未改後端、不重新宣稱完整V驗收。
- 現在請A依 [人工步驟](../a-manual-testing.md) 最新小節重啟Flask、Ctrl+F5，核對排除／預覽／125%字體與跨分頁草稿。B／D真實整合、收貨庫存閉環及規模測試仍待其交付。
