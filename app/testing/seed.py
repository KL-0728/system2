from datetime import timedelta
from app.extensions import db
from app.models import Store, Product, Inventory, SalesDaily, SalesImportBatch, User, Order, ReplenishmentRun
from app.services.clock import business_now, utc_naive
from app.testing.factories import require_fixture_mode, make_order, make_run


def seed_inventory_sales():
    # Explicit checked count baseline; historical seed must never deduct stock again.
    now = business_now()
    products = db.session.execute(db.select(Product)).scalars().all()
    stores = db.session.execute(db.select(Store)).scalars().all()
    actor = db.session.execute(db.select(User).where(User.username == 'admin')).scalar_one()
    for store in stores:
        batch = SalesImportBatch(store_id=store.id, source_batch_id='A03-HISTORY-14D', payload_hash='0'*64,
            import_mode='historical', actor_id=actor.id, created_at=utc_naive(now),
            snapshot={'synthetic': True, 'baseline_checked': True, 'stock_effect': 0})
        db.session.add(batch)
        db.session.flush()
        for product in products:
            db.session.add(Inventory(store_id=store.id, product_id=product.id, physical_qty=20,
                unsellable_qty=0, book_physical_qty=20, book_unsellable_qty=0,
                counted_at=utc_naive(now), updated_at=utc_naive(now)))
            for days in range(14):
                end = now - timedelta(days=days)
                db.session.add(SalesDaily(store_id=store.id, product_id=product.id, business_date=end.date(),
                    interval_start=utc_naive(end - timedelta(days=1)), interval_end=utc_naive(end),
                    sold_qty=20, was_stockout=False, is_open=True, batch_id=batch.id,
                    import_mode='historical', applied_at=None, movement_id=None))
    db.session.flush()


def seed_module_data(module):
    require_fixture_mode()
    if not db.session.execute(db.select(Inventory.id).limit(1)).first():
        seed_inventory_sales()
    if module == 'D' and not db.session.execute(db.select(Order.id).where(Order.fixture_only.is_(True)).limit(1)).first():
        for store in db.session.execute(db.select(Store)).scalars():
            make_order(db.session, store_id=store.id)
    if module == 'C' and not db.session.execute(db.select(ReplenishmentRun.id)
            .where(ReplenishmentRun.model_version == 'controlled-test-v1').limit(1)).first():
        for store in db.session.execute(db.select(Store)).scalars():
            make_run(db.session, store_id=store.id)
