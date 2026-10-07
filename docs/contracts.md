# 共用合約 v1

此檔於 A03 完成後凍結；目前 A02 定義共用基礎，完整跨模組合約待 A03。

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

規格及不可變紀錄不得為通過測試而改寫。後續跨模組欄位與 DTO 詳細定義由 A03 補齊後一起凍結。
