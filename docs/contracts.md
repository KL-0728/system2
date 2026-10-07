# 共用合約 v1

本檔於 A03 發布時凍結為 v1。Python 型別與驗證在 app/contracts.py，模型欄位精確型別／nullable／FK／唯一鍵見 docs/schema.md。相容新增採新 migration；不改已發布 revision 或既有欄位意義。

## A → 全員

- 服務不自行 commit；最外層路由／CLI 使用 app.services.version.transaction 統一 commit／rollback。
- 先 authorize_store(actor, store_id, roles)，再 lock_store(store_id, expected_version)。登入帳號由 g.user 取得，不信任前端角色或門市關聯。不可存取物件回404，角色拒絕403，未登入401。
- 鎖順序：門市 id 升冪 → 草稿／訂單 id → 訂單品項 id → 庫存 product_id → shipment／receipt／variance／authorization id → 冪等來源鍵。全部寫入者先取得門市鎖；不可反向鎖定。需要多門市時先一次依 id 排序取得全部門市鎖。
- 有效銷售、盤點、收貨、訂單、政策、履約變更均在同一交易呼叫 bump_store(locked_store)，讀取版本的確認流程須在鎖內重驗。Store.calculation_version 為整數，初始1；inventories.version 與草稿／履約 version 為各資源版本，不可混用。
- business_now() 回 aware UTC datetime；server_now() 永遠是真實 UTC；DB DateTime 存 UTC naive，僅經 utc_naive／aware 轉換。顯示 Asia/Taipei。round_window(now) 回本日21:00 B 與22:00截止；非開放時段不得生成新日常預覽。時鐘 API 暫留服務，A04補管理畫面。
- record_event(actor_id, store_id, action, entity, old, new) 追加稽核，不 commit。保存真實及業務時間與 request_id；敏感資料不得放 old/new。
- Decimal JSON 使用十進位字串（例如 `"20.125"`），未知為 null；不用 float。時間 JSON 為含 UTC offset ISO8601。所有業務數量使用 int，bool 不是合法數量。
- DomainError(code, message, status=422, details={}) 回 `{"error":{"code":"VERSION_CONFLICT","message":"資料已更新，請重新核對","details":{"current_version":2},"request_id":"…"}}`。
- 400 格式／CSRF，401 未登入，403 角色拒絕，404 不存在或跨店，409 版本／冪等／風險衝突，422 業務錯誤，503 缺少供應者，500 未知錯誤。未知錯誤不得回傳堆疊／連線。
- POST／PATCH／DELETE 均須 CSRF；GET /api/auth/csrf，送 X-CSRFToken。session cookie HttpOnly／SameSite=Lax，正式 Secure，正式不可 debug。

## 共用模型

identity.py：Store／User／UserAcknowledgement；catalog.py：Product／StoreProduct／PolicyVersion／DeliveryCycle；audit.py：AuditEvent／BusinessClock。數量政策集中於版本化 PolicyVersion.parameters，初始預設值見 app.seed.POLICY。

規格及不可變紀錄不得為通過測試而改寫。以下為跨模組固定介面。

## 注入與模組責任

在各自 `app/modules/{inventory,ordering,fulfillment}/services.py` 的 install() 呼叫 `register_provider(name, instance)`；在相鄰 routes.py 的 bp 增加 spec 第11節 API。factory 已統一註冊三個 blueprint，無須修改共用 api.py／app/__init__.py。業務服務仍依 agent.md 放 app/services/，模型依既定負責檔維護。

| 插槽 | 真實提供者 | 消費者 | 方法（所有參數為 keyword-only） |
| --- | --- | --- | --- |
| open_orders | D | B、C | get_open_orders(store_id, baseline_at, protection_end, evaluated_at, session) → OpenOrdersDTO |
| runs | B | C | get_run(run_id, store_id, actor_id, session) → RunDTO；evaluate(run_id, store_id, actor_id, cycle_id, final_quantities, manual_confirmations, evaluated_at, session) → RunDTO |
| integrity | B | C | get_integrity(store_id, product_id, baseline_at, session) → IntegrityDTO |
| inventory_writer | B | D | apply_movement(mutation: InventoryMutation, session) → MovementResult |
| orders | C | D | get_order(order_id, store_id, actor_id, session) → OrderDTO |
| fulfillment | D | C | get_summary(order_id, store_id, actor_id, session) → FulfillmentSummaryDTO |

呼叫 `get_provider('open_orders')` 等取得服務；缺服務503，禁止自行回退。消費者傳入同一 db.session；跨服務不新開 session、不 commit。讀取提供者須核對 actor_id 與門市權限；寫入者仍由外層身份及門市鎖保障。供應者回傳門市、版本及資源 ID，消費者須核對與請求一致。

B 自己的生成 API 持久化 run／run_items，再透過 runs 插槽供 C 讀取。evaluate 對目前最終數量與人工預測確認重新計算時序、容量及當下風險，不覆寫歷史 run。cycle 改變須用有效輪次重算 L；需改模型輸入時建立新 run，不在舊快照內無聲換值。C 自己實作草稿、確認、token、重要例外理由／勾選、送單、冪等，不由 B 或替身提供成功送單。

## DTO 欄位與 null

所有 ID、版本、件數為整數；DTO datetime 為 aware UTC。資料庫 naive UTC 僅在 ORM 邊界轉換。完整型別見 app/contracts.py；dict 快照為 JSON 相容資料，Decimal／datetime 經 app.json 編碼為字串，tuple 序列化為 JSON array。

- RunDTO：run_id、store_id、cycle_id、store_version；baseline_at（B）、actual_generated_at、data_through_at、risk_evaluated_at、protection_end；model_version、warning_version、items。
- RunItemDTO：run_item_id（持久化後必須有值；未持久化受控計算可 null）、product_id、mode、h、mu、target_stock、raw_qty、suggested_qty、pack_size、lead_days、safety_stock、capacity、policy_version、inventory_version、sources、warnings、input_snapshot、timeline_committed、timeline_with_pending、manual_forecast。
- mode=model／manual 時模型量必須為非負有限 Decimal，suggested_qty 為合法整箱 int。mode=direct／unavailable 時 mu、target_stock、raw_qty、suggested_qty 均 null；direct 不提供精確需求曲線，只可在 output_snapshot 明列不扣銷售的保守容量資料。h=null 表示庫存不可用，不能當0。
- manual_forecast=null 表示未使用；否則含 daily_demand 十進位字串、reason、actor_id、created_at、valid_until、override_id（真實提供者必填）。人工值每輪由 manual_confirmations 的 product_id 明確確認；過期值不可用。
- IntegrityDTO：store_id、product_id、inventory_version、store_version、physical_book、unsellable_book、baseline_counted_at|null、missing_dates、warnings；usable 需有效盤點、無日期缺口及合法帳面；h 僅在 usable 時提供。負帳面／缺口不能用人工值或直接訂購繞過。
- input_snapshot 至少含七日日期／銷售／營業及缺貨標記、盤點基準、入帳來源與缺口、政策版本及當時參數、人工值／期限；output_snapshot 保存公式、整箱、警示與雙版曲線。
- timeline 每個元素含 at、demand、receipts（來源 id／bucket／qty）、ending_stock、stockout_qty、capacity_exceeded；真實 B 必須完整提供。受控替身只提供情境驗證所需欄位，不作公式正確證據。
- FulfillmentSummaryDTO：order_id、store_id、version、items、timeline、tasks。items 含 order_item_id、original_qty、committed_qty、original_shipped_qty、replacement_shipped_qty、sellable_received_qty、damaged_received_qty、confirmed_short_qty、pending_receipt_qty、disputed_qty、status、eta。timeline 含 event id／type／actor／occurred_at／snapshot；tasks 含 id／type／source／due_at／overdue／completed_at／result。逾期由當下業務時間推導，不自動完成業務。
- OrderDTO：order_id、store_id、cycle_id、version、submitted_at、items、confirmation_snapshot。items 含 id、product_id、original_qty、product_snapshot；C 提供不可變原訂量及當時確認快照，D 不覆寫。

範例正常飲料：`{"mode":"model","h":20,"mu":"20","target_stock":"50","raw_qty":"30","suggested_qty":30,"pack_size":6}`；特殊直接雨衣：`{"mode":"direct","h":20,"mu":null,"target_stock":null,"raw_qty":null,"suggested_qty":null,"pack_size":1}`。本例不代表產品計算已完成。

## 未結來源

OpenOrdersDTO 含 store_id、store_version、baseline_at、protection_end、evaluated_at、sources；每筆 OpenSourceDTO 含 source_type、source_id、product_id、quantity、bucket、eta、deduction_expires_at|null、disputed。

- source_type 為 pending／committed／shipment／replacement；source_id 識別該段餘量，例如 `order-item:7:unshipped`、`shipment-item:9:unchecked`、`authorization:4:unshipped`。同一實物餘量不得重複列來源，`(source_type, source_id, product_id)` 在回應內唯一。
- bucket=U／C／RISK；指定品項 totals() 各自彙總。U 必須仍在扣抵期限；C 不得有未決爭議；U／C 的 ETA 必須在 `(B, protection_end]` 且未逾期（ETA < evaluated_at 為逾期；等於 ETA 尚未逾期）。超時／爭議／期外來源保留為 RISK，不直接扣需求。
- 承諾後 U 結束；原始未出貨承諾、shipment 尚未核對、已授權未出補送分段列 C。確認損壞／短收退出原待收；尚未核對餘量留原 shipment，不自動產生短收。首次提案期限內依原請求列 U；已有承諾的變更保留原承諾，爭議餘量列 RISK，細則依 spec 8.2。
- DTO 重複檢查不能代替 D 正確分段；D 須在自身模組測試證明無重複。不同時間 evaluate 的來源／警示集合要重驗，不只比對 DB 版本。

## 庫存同交易寫入

InventoryMutation：store_id、product_id、source_type、source_id、physical_delta、unsellable_delta、expected_version（Inventory.version）、actor_id、occurred_at、reason。delta 為有號整數，損壞實收兩者同增；可售實收只增 physical；損壞報廢／退回兩者同減。B 可因日常銷售產生負帳面，但保留有號量並建對帳阻擋。

MovementResult：movement_id、inventory_version、store_version、physical_book、unsellable_book、replayed。來源唯一為 `(store_id, source_type, source_id, product_id)`；D 使用 receipt_item.inventory_source_id，重試同內容回原結果，不同內容409。來源內容含 actor／occurred_at／理由，重試須沿用原內容。B 驗 expected_version 並遞增 Inventory.version／Store.calculation_version，不提前 commit。

D 在同一最外層交易中取得門市鎖、鎖 shipment／授權／餘量、驗證版本與請求、呼叫 B、寫 receipt／結算／timeline／稽核；全成功才 commit。B 失敗時全部 rollback。A03 的 ControlledInventoryWriter 為可寫入及可寫後失敗的替身，只驗呼叫端交易處理，不是 B 正式庫存服務。

## 確認、警示與冪等

警示固定 v1，code→level 映射在 WARNING_LEVELS；每筆 WarningDTO 為 code、version、message、details，level 由後端映射，dto_dict() 補上 JSON level。`FORECAST_INSUFFICIENT` 在尚未合法採人工或直接模式時為 block；直接模式仍保留資料不足事實於 input_snapshot，以 DIRECT_ORDER important 表達處理後模式。

資料不足、負帳面、庫存缺口與非法數量不能用勾選繞過。每品項重要警示合併一個加強確認；正常資訊只納入逐單確認。完整文案與理由依 spec 第7節。警示／文案版本改變需新預覽。

C 冪等以 `(user_id, store_id, key)` 唯一；count 以 `(store_id, user_id, request_key)`；shipment 以 `(order_id, request_key)`；receipt 以 `(store_id, user_id, shipment_id, request_key)`；授權以 `(variance_id, request_key)`。payload 使用固定欄位、排序鍵、UTF-8 JSON（無 NaN）標準化後 SHA256，重試不得用目前可變草稿重建原內容。

身份／門市核對後先查成功結果，再做 token／截止檢查；鎖內再次查鍵。相同 key 不同內容409；同草稿不同 key 仍僅一張訂單（Order.draft_id 唯一）。新單在鎖內重驗門市版本、草稿版本、token、五分鐘、截止、ETA／扣抵／人工值期限、重要警示及理由。

## 測試／開發替身界線

MODULE_DEV=B 注入受控 open_orders；C 注入 runs／integrity／open_orders／fulfillment；D 注入 inventory_writer／orders。已註冊真實提供者不會被替身覆蓋。一般 demo／production 缺服務503；測試模式可手動 register_provider(test_only=True)。所有開發頁持續明示替身來源。

tests/test_contracts.py 是凍結消費端測試；ControlledOpenOrders 支援 normal／pending／committed／late／disputed／expired；ControlledIntegrity 支援 normal／gap／negative／no_count；ControlledRuns 支援 normal／manual／direct／insufficient／time_risk。成員可在自己的測試建立同型別案例，不修改合約來遷就實作。

`make_run(session, store_id=None, scenario='normal')` 建立持久化 run／run_items，供 C 真實草稿 FK 使用；`make_order(session, store_id=None, product_id=None, quantity=30)` 建立共用正式訂單表工廠資料，Order.fixture_only=True，供 D 自身履約服務測試。兩者只限 test 或明示本機模組開發模式，不可在整合／正式模式旁路確認送單。

正式模型與工廠不是業務服務；B 的庫存／計算、C 的草稿／確認／提交、D 的履約仍由各自實作。A05 關閉所有替身，重新驗真實跨模組原子性與來源；A06 才判定 V 驗收。
