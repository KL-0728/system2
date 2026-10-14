"""Explicit 1000-product MySQL measurement, synthetic isolated test transaction."""
import platform
from datetime import timedelta
from time import perf_counter
from sqlalchemy import event
from app.extensions import db
from app.models import Product, User, StoreProduct, PolicyVersion, Inventory, SalesDaily, SalesImportBatch, DeliveryCycle
from app.seed import POLICY
from app.services.clock import business_now, round_window, utc_naive
from app.services.replenishment import ReplenishmentService


def test_generate_1000_real_products(seeded, client):
    actor=db.session.execute(db.select(User).where(User.username=='manager1')).scalar_one()
    store=actor.stores[0]
    baseline=round_window(business_now())[0]
    batch=db.session.execute(db.select(SalesImportBatch).where(SalesImportBatch.store_id==store.id)).scalar_one()
    products=[Product(sku=f'SCALE{i:04}',name=f'合成商品{i}',pack_size=1) for i in range(990)]
    db.session.add_all(products);db.session.flush()
    policies=[PolicyVersion(store_id=store.id,product_id=p.id,version=1,effective_at=utc_naive(baseline),
        parameters={**POLICY,'lead_days':1,'safety_stock':10,'capacity':100,'pack_size':1}) for p in products]
    db.session.add_all(policies);db.session.flush()
    for p,policy in zip(products,policies):
        db.session.add(StoreProduct(store_id=store.id,product_id=p.id,policy_version_id=policy.id,
            lead_days=1,safety_stock=10,capacity=100))
        db.session.add(Inventory(store_id=store.id,product_id=p.id,physical_qty=20,book_physical_qty=20,
            unsellable_qty=0,book_unsellable_qty=0,counted_at=utc_naive(baseline),updated_at=utc_naive(baseline)))
    sales=[]
    for p in products:
        for days in range(14):
            end=baseline-timedelta(days=days)
            sales.append(dict(store_id=store.id,product_id=p.id,business_date=end.date(),
                interval_start=utc_naive(end-timedelta(days=1)),interval_end=utc_naive(end),sold_qty=20,
                was_stockout=False,is_open=True,batch_id=batch.id,import_mode='historical',version=1))
    db.session.execute(db.insert(SalesDaily),sales);db.session.flush()
    cycle=db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==store.id)
        .order_by(DeliveryCycle.arrival_at)).scalars().first()
    start=perf_counter()
    run=ReplenishmentService().generate(store_id=store.id,actor_id=actor.id,cycle_id=cycle.id,
        expected_version=store.calculation_version,session=db.session)
    elapsed=perf_counter()-start
    print(f'{platform.platform()} / Python {platform.python_version()} / MySQL {db.session.execute(db.text("SELECT VERSION()")).scalar_one()}')
    print(f'1000 products / 14000 historical rows / real providers / generation={elapsed:.3f}s / target=5s')
    assert len(run.items)==1000
    assert all(item.suggested_qty==30 for item in run.items)
    assert elapsed < 5, f'1000-product generation {elapsed:.3f}s exceeds target'
    from test_management import login
    assert login(client).status_code == 200
    statements = []
    engine = db.engine
    def count_query(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', count_query)
    try:
        start = perf_counter()
        response = client.get('/api/inventory/status')
        status_elapsed = perf_counter() - start
    finally:
        event.remove(engine, 'before_cursor_execute', count_query)
    assert response.status_code == 200, response.json
    assert len(response.json['items']) == 1000
    assert all(item['usable'] and item['h'] == 20 for item in response.json['items'])
    assert len(statements) <= 14, len(statements)
    print(f'1000-product inventory status={status_elapsed:.3f}s / SELECTs={len(statements)}')
