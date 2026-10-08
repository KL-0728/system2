# A03 獨立開工基礎發布紀錄

## 最新修正版基準：a03-parallel-v2

2026-10-08：在v1（e39f1dfbe31c84e894cd2a97999efb5dea9d9f2f）上補齊MySQL重新啟動、唯讀環境檢查、人工核對與每次結束回報規則，並支援至少8字元的本機共用示範密碼。A本次明確授權直接提交推送main，不開PR；B／C／D仍使用模組分支及PR。

- 合約v1、36張ORM表及migration head 884e7a53a8c8不變；沒有新增migration或重設資料。
- 發布前本機檢查：demo／test連線及migration皆PASS；pytest為36 passed in 11.61s；四個示範帳號HTTP登入皆200。A回報登入成功及完成跨店人工核對，但對話未逐筆提供最終跨店回應，不宣稱完整V驗收完成。
- main推送後核對該提交的GitHub mysql-tests成功，才建立a03-parallel-v2標記。精確發布SHA以下列指令查詢；v1保留，不移動舊標記。

```powershell
git fetch origin --tags
git rev-parse 'a03-parallel-v2^{commit}'
git merge-base --is-ancestor a03-parallel-v2 origin/main
```

最後一行預期結束碼0；找不到v2標記時，先確認A的發布回報。

### 組員取得修正版與開工

先讀[組員操作入口：現在要做什麼](team-start.md)，依目前狀態選首次安裝、日常啟動、人工核對或PR交接，內含可直接貼給Codex的下一句。此入口整理操作；程式發布基準仍為下述a03-parallel-v2。

尚未開始模組且工作目錄乾淨者執行以下指令；C／D將最後一行換成feat/c-module／feat/d-module。有未提交修改或已有模組分支者，先依agent.md第5.1節保留工作並在自己的分支同步，不重建或覆寫分支。

```powershell
git status --short --branch
git fetch origin --tags
git switch main
git pull --ff-only origin main
git merge-base --is-ancestor a03-parallel-v2 HEAD
git switch -c feat/b-module
```

首次安裝依README建立自己的.env、demo／test DB及migration；已安裝者依「每次重新開工」啟動自己設定的MySQL，再跑scripts/check_environment.py，預期兩行PASS，接著pytest -q，基礎版預期36 passed。A專用start_a_mysql.ps1不適用其他人的新checkout。

每人可在自己的.env設定團隊約定的合成示範密碼；此檔不在GitHub，pull不會帶入A的密碼或資料。新建帳號依DEMO_PASSWORD建立，既有帳號不會因編輯.env自動改密碼。接著依README設定MODULE_DEV及seed-module，沿自己的01→05完成、自測與交接。

組員可貼：「我是B，請依agent.md完成我的整個模組；先確認a03-parallel-v2基準，每階段自測回報並繼續。」C／D換成自己的成員代號。

以下保留v1的發布與檢查紀錄，最新開工基準以本節v2為準。

狀態：A03 基礎已發布，B／C／D 可獨立開工。發布流程在本紀錄推上 main 並核對 CI 後建立 a03-parallel-v1 標記；標記解析到包含本紀錄的實際發布提交。

- 已測程式基準（實際 main 提交）：ef653c73e2b44cfe4a5988a4cc81723e9406e8a0。
- 發布版本：a03-parallel-v1；首次 clone 同步 main，確認 main 包含此標記。標記的精確 SHA 可用 `git rev-parse a03-parallel-v1^{commit}` 取得；公告提交另含本紀錄、文件空白修正及測試環境隔離設定。
- A03 GitHub MySQL 8.4 CI：migration／pytest／db check 步驟全部 success，[執行紀錄](https://github.com/KL-0728/system2/actions/runs/37666023805)。最終發布提交的 CI 可於同一儲存庫 Actions 查看。

- 合約：v1，app/contracts.py 與 docs/contracts.md；完整欄位見 docs/schema.md。
- 共用 schema：36 張 ORM 表；migration 單一 head 884e7a53a8c8（前置 2ce34638ca9a）。
- A01：1c56c7f；A02：0b3e356（GitHub CI success）。
- 本次 A01–A03 已獲使用者明確授權直接 main 提交／推送，不開 PR；B／C／D 仍用個人模組分支及 PR。

## 已執行的基礎檢查

環境：Windows、Python 3.12、MySQL 9.6.0／InnoDB，獨立127.0.0.1:3307。資料庫 system2_a_demo 與 system2_a_test；密碼與 SECRET_KEY 僅存未追蹤 .env。

| 檢查 | 實際結果 |
| --- | --- |
| A02 MySQL 基礎測試 | 6 passed；登入／CSRF／跨店／角色／時鐘／版本／Decimal |
| 全新 .venv-clean 依 requirements 安裝 | 成功 |
| 空 test schema 從零升級兩個 revision | 成功，單一 head；db check 無差異 |
| A03 共用／合約測試 | 36 passed；最後快照守衛重驗2項通過；繼承 MODULE_DEV=C 的隔離測試重驗28項通過 |
| B 獨立 HTTP 檢查 | health／登入／modules/b 200；非啟用模組404；替身來源可見 |
| C 獨立 HTTP 檢查 | 同上；持久化 run／run_items 可用於 C 真實草稿 FK |
| D 獨立 HTTP 檢查 | 同上；fixture_only 正式表工廠訂單；原訂30件 |
| MySQL 門市版本鎖 | 兩條連線序列化，後取得鎖者讀到新版本2 |
| 受控庫存寫後失敗 | 回滾後帳面仍20、無異動；成功測試增至30，重試不再加；異內容409 |
| 來源／阻擋／null | U／C／期外／逾期／爭議、庫存缺口／負帳面、人工／直接模式與時間風險測試通過 |
| 示範安全重設 | 本機 demo 含 D 工廠資料重設成功；兩店20庫存列、280歷史銷售列 |
| 登入限流 | 5次錯密碼401，第6次429 |
| 秘密排除 | .env／instance／.venv／.venv-clean 均忽略 |

上述為 AI 自動測試／HTTP 客戶端檢查，未宣稱瀏覽器、手機或人類實測完成。跨模組 B／C／D 真實服務尚未實作；V01–V50 未驗收。

## 三人的下一步

1. 發布後依 README「A03：B／C／D 各自開工」首次 clone／同步 main，再開自己的 feat/b-module、feat/c-module、feat/d-module；各有自己的本機 demo／test DB。
2. 執行 migration、seed-demo、指定 MODULE_DEV 與 seed-module、check_module 及合約測試，核對替身標示與正常／錯誤路徑。
3. 沿自己的01→05製作、自測，更新自己的 docs/handoffs/B.md、C.md、D.md，不等待其他人成果或 A 每步合併。
4. 模組末尾給完整人工實測指南；人類實測後才授權提交／推送 Ready PR，不自行合併。未完成實測可授權 Draft 保存進度。

實際命令、身份、資料、URL、預期結果與可貼啟動句見 README 及各人交接檔。A 的完整紀錄見 docs/handoffs/A.md。

## 界線與已知限制

- 一般 demo／production 不自動注入替身；缺服務503。開發替身及工廠不能當正式計算、送單或庫存已入帳的證據。
- A04 管理畫面、A05 真實整合、A06 全部 V／MySQL 業務併發／效能／手機／三人易用性、A07 影片未完成。
- 基準 migration 供向前升級；舊自動 downgrade 有 MySQL 外鍵索引限制，不作回退保證，保留已發布 revision。空 test 重建工具明確驗空才操作，不能當一般資料清理。
- main 分支保護已透過 GitHub API 設定並讀回：PR至少1人審核、過期審核失效、mysql-tests必要檢查且需最新main、對話解決、禁止強推／刪除。
- 管理者不強制受保護規則（配合本次 A 直接main授權）；使用者個人儲存庫未設定組織級指定推送者限制。平台不保證只有A能合併，仍依團隊規則由A審核合併，B／C／D不可直接推main。

發布宣布：共用基礎 A03 已完成，程式基準 ef653c7、合約 v1，正式發布標記 a03-parallel-v1。大家可以開始，各自在自己的模組分支依01→05完成、自測、人工實測後開PR；不必等其他人或A逐步合併。
