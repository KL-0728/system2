# 全專案後續檢查與優化（2026-10-13）

本次身份 A，任務為全專案檢查與整合補修。使用者授權修正並推上 main，並追加顯示密碼功能。起始工作目錄乾淨，fetch／pull --ff-only 成功；HEAD 與 origin/main 均為 `f3a1d7a`，任務分支 `fix/a-project-audit`。保留規格、既有 migration、demo 資料及 .env，不部署、不改 B／C／D 分支，也不使用 AI 子代理。

## 實際發現與修正

| 視角 | 原行為／問題 | 修正與影響 |
| --- | --- | --- |
| 使用者／登入 | 錯誤密碼直接顯示 JSON；未登入開訂單頁沒有返回原頁的登入流程；未建立示範時鐘時登入頁失敗 | 表單顯示中文錯誤、保留帳號及清空密碼，可直接重試；HTML 頁面引導登入並返回原頁；API 維持 JSON，錯誤狀態碼保留；返回網址限制於本站 |
| 使用者／密碼 | 密碼無法暫時顯示核對 | 登入及管理帳號的密碼欄加入顯示／隱藏按鈕，預設隱藏；有鍵盤操作、aria-controls／aria-pressed；只改輸入欄顯示，不查詢或回傳既有密碼 |
| 資料安全／輸入 | 訂購 `store_id=bad` 被視為未指定，默默回到預設門市；草稿、頁碼、重複參數或超長商品 ID 未一致拒絕 | 統一限制正整數及範圍，在轉換／查詢前拒絕無效值；不影響合法省略門市時的原預設行為；JSON ID 同樣驗證 |
| 使用者／管理 | 儲存設定期間仍可改欄位或切換分類；回應後重新載入會覆蓋途中編輯 | 儲存期間停用設定欄位、分類及紀錄選擇，完成／失敗後還原，既有唯讀欄位仍維持唯讀 |
| 使用者／訂單 | 快速切頁後，較晚回來的舊回應可能覆蓋新頁；成功重試後仍顯示舊錯誤 | 只套用最後一次切頁的回應，重新讀取時清除舊錯誤 |
| 工程／庫存效能 | 資料管理逐商品重複讀取完整性、庫存、盤點、銷售及待辦 | 使用既有正式完整性批次介面，批次查詢當輪盤點／銷售／對帳紀錄；舊盤點仍保留完整帳務驗證，未放寬缺口或負帳面阻擋 |
| 工程／錯誤復原 | 超過請求大小限制或資料庫／時鐘不可用時，錯誤畫面可能再次失敗 | 錯誤復原不重解析已拒絕的表單；共用畫面容許時鐘來源不可用；保留 413 等失敗狀態及請求編號 |

涉及 F01、F04、F09、spec 9.1／9.2／12 及 V20／V24 的相關回歸。沒有改補貨公式、警示、確認責任、原訂量、庫存交易或跨服務合約。

## 自測證據

新增回歸測試使用本機 MySQL 9.6／3307、獨立 `system2_a_test`，交易結束回滾。將原 `f3a1d7a` 匯出至忽略的 instance 目錄，對同一隔離 test DB 依序跑三個新增案例：三項均失敗，分別證實無效門市回 200、登入錯誤回 JSON，以及 60 商品狀態查詢使用 **425 次 SELECT**。修正後同一案例使用 **14 次 SELECT**；包含負帳面及舊盤點，完整性欄位與正式逐項介面一致。

瀏覽器使用真實 Edge，1280／390／320px；已確認登入顯示／隱藏密碼、Enter 鍵操作、錯誤重試、重新登入後返回訂單、管理密碼、儲存期間停用及還原，以及訂單分頁舊回應不覆蓋。另重跑既有管理、B／C／D 真實閉環、庫存及人工／直接模式，共 **21 項通過**。截圖保存在忽略的 `instance/browser-check/audit-login-*.png`／`audit-admin-*.png`，已檢視 320px 畫面，無橫向溢出。訂單分頁競態使用明示唯讀回應測試資料，不作正式送單證據；真實閉環由既有 browser_a_completion 驗證。

Node 既有事件測試 **2 項通過**；JS 語法、compileall、pip check、git diff --check 通過。基準完整後端為 383 項通過，有沙箱無權寫 pytest 快取的警告；後續以 `-p no:cacheprovider` 執行。中間新增案例的兩次失敗為測試預期錯誤（422 狀態及 JSON 日期序列化），已修正後重驗；瀏覽器測試亦修正返回網址匹配及按鈕切換後的定位，不把失敗記為通過。

最後大體積表單／時鐘錯誤復原防護完成後，新增 Edge 案例再次執行 **7 passed／15.11 秒**；完整後端結果亦為此最終程式版本。

最終完整後端 **395 項通過，206.83 秒，無警告**。`flask db check` 無新增結構差異，`db heads` 單一 `884e7a53a8c8`，沒有新增 migration。規模測試於 Windows 11／Python 3.12.6／MySQL 9.6.0：1000 商品、14000 歷史列、真實提供者計算 **1.177 秒**，低於既有五秒目標；1000 商品庫存狀態查詢 **0.131 秒、10 次 SELECT**，1 項通過。這是本機合成資料測量，舊盤點路徑仍保留完整逐日驗證，不宣稱所有資料形態都有固定查詢次數。

可複製自測命令（先完成環境檢查；以下均使用獨立 test DB）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q tests/browser_audit.py tests/browser_a_completion.py tests/browser_inventory.py tests/browser_forecast_modes.py -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -s tests/performance_integration.py -p no:cacheprovider
node --test tests/ordering_ui.test.cjs
$env:APP_ENV='test'
.\.venv\Scripts\python.exe -m flask --app wsgi db check
.\.venv\Scripts\python.exe -m flask --app wsgi db heads
Remove-Item Env:APP_ENV
```

預期後端 395 passed、瀏覽器 21 passed、規模 1 passed、Node 2 passed；瀏覽器需要本機 Playwright 與 Edge，跳過不算通過。GitHub main 保護已唯讀確認，必要檢查 mysql-tests，未要求管理者強制套用保護；發布保留原設定。

## 組員人工核對

在 `C:\Users\user\Desktop\system2`；若本機 Flask 正在執行，先 Ctrl+C 停止。同步 main 時保留自己的工作，按 agent.md 適用流程操作；不用重設或重新 seed-demo。

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
$env:APP_ENV='demo'
Remove-Item Env:MODULE_DEV -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

預期 demo／test 兩行 PASS，migration head `884e7a53a8c8`。DB 沒啟動時先依 README 啟動既有實例，勿覆蓋 .env 或初始化資料。

1. 無痕開啟 http://127.0.0.1:5000/store/orders → 導向登入。輸入 manager1 與本機 .env 的 DEMO_PASSWORD；先按「顯示密碼」→內容可見且文字改「隱藏密碼」，再按一次→隱藏，輸入不變。Enter／Space 可操作按鈕，不應送出表單。
2. 先以錯誤密碼登入 → 同頁顯示「帳號或密碼錯誤」、保留 manager1、密碼清空；再填正確密碼 → 返回訂單頁。API `/api/auth/me` 的 username 應為 manager1。有效 API 權限與 CSRF 仍須通過，不會因顯示密碼而跳過。
3. 在登入中的同一視窗開啟 http://127.0.0.1:5000/api/orders?store_id=bad → 400／INVALID_INPUT；`?page=0` 同樣拒絕，不回預設頁。從 `/api/auth/me` 取得本店門市 ID，合法指定本店 → 200，合法指定他店 → 404；不要混淆帳號 ID 與門市 ID。
4. 開「資料管理」→庫存、盤點與銷售狀態正常顯示；重新整理前後數量不變，讀取不新增庫存異動。既有待對帳及缺口仍顯示，不能繞過送單限制。
5. 登出，admin 使用同一來源的示範密碼登入，開「管理設定」→「帳號」。新填的密碼可顯示／隱藏；切換帳號後密碼應清空並預設隱藏；留空儲存既有帳號仍保留原密碼。不要為測顯示而重設團隊帳密。
6. 用可辨識的本機示範商品修改名稱並儲存；較慢網路下，途中欄位／分類／其他商品選擇不可操作，完成後恢復。重新點該商品核對儲存值；商品代碼維持唯讀。需復原時以新 revision 把名稱改回。
7. 有多頁訂單時連續切頁，最後選擇的頁面不得被舊回應蓋回。將視窗縮到 390／320px 重做密碼按鈕及管理欄位核對，按鈕與輸入不得橫向溢出。

如失敗，回報 main SHA、角色、步驟、實際／預期差異與錯誤文字，不提供密碼。真人三人計時、完整逐項 V 驗收及影片交付沿用既有待辦，本次不代填通過。

## 發布結果

本機驗證完成，依本次授權在任務分支提交，先推送候選版確認 mysql-tests，再以 fast-forward 更新 main；發布及遠端 SHA／CI 的實際結果由本次交付回覆及 GitHub 提交檢查紀錄確認。保留 main 保護、mysql-tests 必要檢查與原歷史，沒有 force push、重設資料或部署。團隊下一步為同步發布版本、重啟 Flask，依上述步驟核對；不需另行授權本次已明確要求的 main 推送。
