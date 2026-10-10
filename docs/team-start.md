# 組員操作入口：現在要做什麼

**A已合併C、要預覽本次補修：請先照[本機預覽與逐步人工實測](a-manual-testing.md)操作。** 包含啟動網址、草稿恢復、排除、1000件、手機排版及預期結果。使用者已授權將補修提交、推送至 `fix/a-c-order-validation`；主線合併另由A安排。

**所有後續畫面請沿用[共用配色與排版指引](ui-guidelines.md)。** 繼承base.html與app.css，使用淺灰＋靛紫配色；模組特殊樣式獨立維護。修正合併main後，組員同步origin/main才會取得新版。

這份文件說明操作，分工與授權規則仍以[agent.md](../agent.md)為準。適用A03共用基礎；B／C／D真正功能完成後，使用各模組交接檔提供的功能網址與案例。

## 1. 先選現在的狀態

「貼給Codex」是貼在聊天框；PowerShell程式區塊才是在專案根目錄的終端機執行。每一步成功才繼續，遇到錯誤就停在該步。

| 現在狀態 | 現在做什麼 | 可貼給Codex的下一句（B範例，C／D換成自己的代號） |
| --- | --- | --- |
| 第一次開工 | 讓Codex核對發布基準、建立自己的模組分支、協助本機環境，再連續製作01→05 | 我是B，請依agent.md完成我的整個模組。先核對GitHub、A03發布基準與本機環境，在feat/b-module連續完成B01到B05；每階段自測回報並繼續，最後給我可直接操作的人工實測指南與下一句指令。本次先不提交推送、不開PR、不合併。 |
| 換天／中斷後回來 | 保留現有成果，沿原分支接續，不重新初始化 | 我是B，請核對交接紀錄、同步狀態及本機環境，保留已有修改，從尚未完成的階段繼續我的模組到B05。 |
| Codex正在連續製作 | 閱讀每階段改動與自測結果，有問題才插話 | 正常情況無須輸入下一句，Codex會繼續；不要每階段等A合併。 |
| AI自測完成、輪到人工核對 | 依本次指南啟動自己的模組，測正常與錯誤情境 | 請根據我目前分支與實際環境，直接列出現在要執行的命令、帳號、完整網址、每一步預期結果，以及完成後可貼的回報文字。 |
| 操作失敗／看不懂 | 貼步驟編號、完整命令或網址、登入帳號、實際回應；不貼秘密 | 我在步驟＿＿，以帳號＿＿操作＿＿，預期＿＿，實際＿＿。請先定位問題、自測修正，再只列出需要重測的步驟。 |
| 人工檢查完成 | 依本次指南逐項回報結果，未測項寫未測 | 我是B，人工實測結果：步驟1＿＿、步驟2＿＿、錯誤情境＿＿；未測項＿＿。請核對是否足夠交接，先不要提交推送。 |
| 模組可交接，授權發布PR | 提交自己的任務檔案，推送自己的分支，交A審核 | 我是B，我已依指南實測通過，請檢查差異，只提交本次B模組檔案，推送feat/b-module並建立交給A審核的Ready PR，填妥測試與待整合清單，不合併main。 |
| Ready PR已交A | 等待集中審核；有修正要求時在自己的分支處理 | 暫無需操作，不自行合併或重新開另一個模組。 |

不確定某一步是否通過時可以先貼實際輸出，無須猜。只說「好了」不足以證明特定權限或交易案例已通過。

## 2. 第一次安裝：只做一次

先依[發布紀錄](parallel-ready.md)核對基準與個人分支；以下在自己的checkout執行，不複製A的.env或資料目錄。

1. 確認Python與MySQL已安裝、MySQL正在執行，建立自己的空demo／test DB及專用帳號。例如B用system2_b_demo、system2_b_test。DB尚未建立或不清楚服務時，貼給Codex：「請檢查我的本機MySQL服務、連接埠及獨立demo／test DB設定，協助完成首次環境；保留已有資料，不重設或覆蓋.env。」Codex可檢查環境並協助設定，不能猜測管理者密碼或宣稱DB已建立。
2. 建立Python環境與本機設定：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
```

3. 編輯.env：DATABASE_URL／TEST_DATABASE_URL填自己的MySQL帳號、DB密碼、實際連接埠及DB名稱；SECRET_KEY填上一步本機產生的值。DEMO_PASSWORD保留團隊合成示範值managerps即可。**MySQL連線密碼和網頁登入密碼是兩件事**，不要因網頁登入失敗修改DATABASE_URL。
4. 首次對兩個DB套用migration，再只在demo建立示範資料：

```powershell
$env:APP_ENV='test'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
$env:APP_ENV='demo'
.\.venv\Scripts\python -m flask --app wsgi db upgrade
.\.venv\Scripts\python -m flask --app wsgi seed-demo
.\.venv\Scripts\python scripts/check_environment.py
.\.venv\Scripts\python -m pytest -q
```

預期：migration成功、示範資料建立成功、兩行PASS；A03基礎版為36 passed，模組新增測試後數量可增加，不要求永遠等於36。已有示範資料時跳過seed-demo；遇到「已有門市」不要重設資料。

## 3. 每次啟動：選自己的模組

先啟動.env所連到的MySQL。A既有3307實例可用scripts/start_a_mysql.ps1；B／C／D啟動自己的MySQL服務。再執行scripts/check_environment.py，兩行PASS後，於PowerShell設定自己的身份（只選一行）：

```powershell
$env:MODULE_DEV='B'
# C組員改為 $env:MODULE_DEV='C'
# D組員改為 $env:MODULE_DEV='D'
$env:APP_ENV='demo'
.\.venv\Scripts\python -m flask --app wsgi seed-module $env:MODULE_DEV
.\.venv\Scripts\python -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

預期終端機顯示Running on http://127.0.0.1:5000。這個視窗讓Flask繼續執行；瀏覽器操作不需輸入終端機。要執行其他命令就另開終端機，或先Ctrl+C停止Flask。每個新PowerShell都有自己的環境變數，需重新設定APP_ENV／MODULE_DEV。

.env可編輯MODULE_DEV=B／C／D或留空；修改後要重啟Flask。上面使用PowerShell設定的環境變數優先於.env；若想改回由.env決定，在啟動用視窗執行`Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue`後重啟。也檢查APP_ENV是否殘留test，避免用空的test DB登入。

| 你是誰 | 使用帳號 | 密碼（首次依新範本建資料） | 登入後開啟 |
| --- | --- | --- | --- |
| B | manager1 | managerps | http://127.0.0.1:5000/modules/b/ |
| C | manager1 | managerps | http://127.0.0.1:5000/modules/c/ |
| D | operator；測店長收貨時用manager1 | managerps | http://127.0.0.1:5000/modules/d/ |

登入網址：http://127.0.0.1:5000/login。manager1屬DEMO1、manager2屬DEMO2；admin是示範管理者。managerps僅為合成示範密碼，不用於真實帳號；既有DB若使用不同密碼，改.env不會自動改帳號。需要統一時貼：「請將我本機demo的四個示範帳號密碼統一為managerps並同步.env，保留現有業務資料，逐一驗證登入，不提交.env。」不要為了改密碼執行reset-demo。

## 4. 如何判斷錯誤是不是預期

| 看到的結果 | 判斷與當下動作 |
| --- | --- |
| MySQL 2003／Connection refused或大量DB errors | 先確認MySQL實際連接埠與服務，再跑check_environment；不要重設資料或改SQLite。 |
| INVALID_CREDENTIALS／帳號或密碼錯誤 | 確認APP_ENV=demo、帳號拼字、實際帳號密碼；輸入managerps不含引號。既有DB可能仍是舊密碼，交Codex定位。 |
| HTTP 429 | 登入短時間嘗試太多，等一分鐘再試；不要移除限流。 |
| NOT_FOUND／此模組開發模式未啟用（404） | 若開的是別人模組，這是預期；若開的是自己模組，檢查MODULE_DEV並重啟Flask。 |
| 非真實跨模組整合 | 預期的測試來源標示，表示可獨立開發，不代表真實功能完成。 |
| pytest有warning | 記錄warnings summary的類型、來源與訊息，勿只報數量；由Codex判斷需不需要處理。 |

## 5. 跨店權限：先查身份，再看資料

這是共用權限檢查。兩個一般分頁會共用登入狀態；使用一般視窗和無痕視窗區分兩個帳號。以下每步都在指明的視窗做。

1. **一般視窗**以manager1登入，開啟 http://127.0.0.1:5000/api/auth/me，先確認username為manager1，再從stores陣列找DEMO1的id。最外層id是帳號id，不能拿來組門市網址。
2. **無痕視窗**以manager2登入，開啟同一網址，確認username為manager2，從stores找DEMO2的id。門市id會因資料建立而不同，不假設是1／2。
3. **回一般視窗**再開/api/auth/me確認仍是manager1。假設查到DEMO1=3、DEMO2=4，接著開：http://127.0.0.1:5000/api/stores/3/context → 應顯示DEMO1資料；http://127.0.0.1:5000/api/stores/4/context → 應回錯誤（404）。實際id不同就替換網址中的數字。
4. **無痕視窗**仍是manager2，以同樣方式驗證：讀DEMO2成功、讀DEMO1回404。若manager1讀到DEMO2資料，先在同一視窗查/api/auth/me；確認仍是manager1時就是權限問題，回報並停止宣稱通過。

可貼回報（依實際結果填寫，未測寫未測）：

```text
目前分支／版本：＿＿
啟用模組：＿＿；自己的模組頁：＿＿；其他模組頁：＿＿
一般視窗身份：＿＿；DEMO1門市id：＿＿
無痕視窗身份：＿＿；DEMO2門市id：＿＿
manager1讀DEMO1：＿＿；manager1讀DEMO2：＿＿
manager2讀DEMO2：＿＿；manager2讀DEMO1：＿＿
其他錯誤或warning：＿＿
請判斷還需要檢查什麼，並給我下一句指令。
```

## 6. 檢查完成後

共用基礎通過後繼續自己的模組01→05，不必每階段重做所有基礎操作。模組完成時，仍要做本模組真實功能的正常／錯誤案例；只會登入、基礎頁可開、pytest通過，不能替代本模組人工實測。由Codex依本次變更列出需要重測的範圍。

準備交接時使用第1節對應的下一句；未授權提交推送時先留本機，已授權則不重複詢問。PR交A後等待集中審核；跨模組真實整合由A05／A06完成。
