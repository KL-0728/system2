import os
from datetime import datetime, time, timezone
from app.extensions import db
from app.models import Store, User, Product, PolicyVersion, StoreProduct, DeliveryCycle, BusinessClock
from app.services.clock import utc_naive, server_now

POLICY = dict(review_days=1, absolute_large_qty=100, deviation_floor=100,
    deviation_multiplier=3, confirmation_minutes=5, deduction_minutes=60,
    supply_response_minutes=60, receipt_minutes=60, variance_hours=24,
    contact_minutes=60, manual_valid_days=7, model_version='sma7-periodic-v1', warning_version='1')


def seed_demo():
    password = os.environ.get('DEMO_PASSWORD', '')
    if len(password) < 12:
        raise ValueError('DEMO_PASSWORD 至少12字元，僅放本機 .env')
    if db.session.execute(db.select(Store.id).limit(1)).first():
        raise ValueError('資料庫已有門市，拒絕覆蓋；請使用安全 demo 重設')
    baseline = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    db.session.add(BusinessClock(id=1, business_anchor=utc_naive(baseline),
        server_anchor=utc_naive(server_now()), paused=True))
    stores = [Store(code=f'DEMO{i}', name=f'虛構示範門市{i}', cutoff=time(22)) for i in (1, 2)]
    db.session.add_all(stores)
    products = [Product(sku=f'SKU{i:02}', name=name, pack_size=6 if i == 1 else 1)
        for i, name in enumerate(['飲料', '雨衣', '泡麵', '衛生紙', '礦泉水', '餅乾', '咖啡', '茶飲', '果汁', '紙巾'], 1)]
    db.session.add_all(products)
    db.session.flush()
    for username, role, allowed in [('manager1', 'manager', [stores[0]]),
            ('manager2', 'manager', [stores[1]]), ('operator', 'operator', []), ('admin', 'admin', [])]:
        user = User(username=username, role=role, stores=allowed)
        user.set_password(password)
        db.session.add(user)
    for store in stores:
        for product in products:
            policy = PolicyVersion(store_id=store.id, product_id=product.id, version=1,
                effective_at=utc_naive(baseline), parameters={**POLICY, 'lead_days': 1,
                    'safety_stock': 10, 'capacity': 100, 'pack_size': product.pack_size})
            db.session.add(policy)
            db.session.flush()
            db.session.add(StoreProduct(store_id=store.id, product_id=product.id,
                policy_version_id=policy.id, lead_days=1, safety_stock=10, capacity=100))
        from datetime import timedelta
        for days in (1, 2, 3):
            db.session.add(DeliveryCycle(store_id=store.id, baseline_at=utc_naive(baseline),
                cutoff_at=utc_naive(baseline + timedelta(hours=1)),
                arrival_at=utc_naive(baseline + timedelta(days=days))))
    db.session.flush()
