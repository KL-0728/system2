# A03 獨立開工基礎發布紀錄

狀態：候選版，尚未宣布組員開工。程式與本機證據已備妥，待本次 A03 main 提交與 GitHub CI 核對後更新為已發布。

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
| A03 共用／合約測試 | 36 passed（含新持久化 C run 工廠；最終提交前再驗受影響項目） |
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
- main 分支保護：發布前待設定及讀回確認；不將文件宣稱為平台已設定。
