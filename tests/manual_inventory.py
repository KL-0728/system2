"""Run B01 numerical checks in an empty, local TEST DB; always roll back.

This is a service-level guide. Sales rows are synthetic inputs, not the B02
CSV importer. No web UI, real C ordering, or real D receiving is claimed.
"""
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from app import create_app
from app.contracts import InventoryMutation
from app.extensions import db
from app.models import (BusinessClock, Inventory, InventoryCount,
    InventoryCountRevision, InventoryReconciliation, SalesDaily, SalesImportBatch, Store, User)
from app.providers import get_provider
from app.seed import seed_demo
from app.services.clock import business_now, utc_naive
from app.services.errors import DomainError


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS: ' + message)


def conflict(code, call):
    try:
        call()
    except DomainError as exc:
        check(exc.code == code, f'{code} (HTTP {exc.status})')
    else:
        raise AssertionError('Expected ' + code)


def daily_input(service, row, actor, b, sold, key):
    # Synthetic test preparation: the seed's checked count becomes prior-day,
    # then the current interval is legitimately not yet covered by a count.
    row.counted_at = utc_naive(b - timedelta(days=1))
    db.session.flush()
    movement = service.apply_movement(mutation=InventoryMutation(row.store_id, row.product_id,
        'sales', key, -sold, 0, row.version, actor.id, b, 'Synthetic B01 daily input'), session=db.session)
    batch = SalesImportBatch(store_id=row.store_id, source_batch_id=key, payload_hash='0' * 64,
        import_mode='daily_posting', actor_id=actor.id, created_at=utc_naive(business_now()),
        snapshot={'synthetic': True, 'B02_importer': False})
    db.session.add(batch)
    db.session.flush()
    daily = db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id == row.store_id,
        SalesDaily.product_id == row.product_id, SalesDaily.business_date == b.date())).scalar_one()
    daily.batch_id, daily.sold_qty, daily.import_mode = batch.id, sold, 'daily_posting'
    daily.applied_at, daily.movement_id = utc_naive(business_now()), movement.movement_id
    db.session.flush()


def run():
    app = create_app({'APP_ENV': 'test', 'MODULE_DEV': ''})
    with app.app_context():
        try:
            # App config validates mysql+pymysql, localhost, *_test and demo separation.
            for table in db.metadata.tables.values():
                if db.session.scalar(db.select(db.func.count()).select_from(table)):
                    raise RuntimeError(f'Test DB must be empty; refusing to change {table.name}.')
            os.environ['DEMO_PASSWORD'] = 'Synthetic-B01-manual-only'
            seed_demo()
            service = get_provider('inventory_writer')
            store = db.session.execute(db.select(Store).where(Store.code == 'DEMO1')).scalar_one()
            actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
            rows = db.session.execute(db.select(Inventory).where(Inventory.store_id == store.id)
                .order_by(Inventory.product_id)).scalars().all()
            row, negative = rows[:2]
            b = business_now()
            print(f'B01 real service; TEST DB {db.engine.url.host}:{db.engine.url.port}/{db.engine.url.database}')
            print('Synthetic manager1 / DEMO1; count cutoff 2026-10-08 21:00 Asia/Taipei; units: pieces.')
            print('Sales posting rows below are controlled persisted inputs, not the B02 CSV service.')
            daily_input(service, row, actor, b, 2, 'manual:daily')
            check(row.book_physical_qty == 18, '21:00 book=18 after sales input')
            clock = db.session.get(BusinessClock, 1)
            clock.business_anchor = utc_naive(b + timedelta(minutes=10))
            db.session.flush()
            receipt = service.apply_movement(mutation=InventoryMutation(store.id, row.product_id,
                'receipt', 'manual:receipt', 10, 0, row.version, actor.id,
                b + timedelta(minutes=10), 'Synthetic receipt input'), session=db.session)
            check(receipt.physical_book == 28, '21:10 receipt +10 -> current book=28')
            clock.business_anchor = utc_naive(b + timedelta(minutes=20))
            db.session.flush()
            args = dict(store_id=store.id, product_id=row.product_id, actor_id=actor.id, cutoff_at=b,
                physical_qty=20, unsellable_qty=0, expected_version=row.version, request_key='manual:count',
                reason='Synthetic physical count', session=db.session)
            first = service.submit_count(**args)
            check(first.physical_delta == 2 and row.book_physical_qty == 30, 'First count delta=+2 -> current book=30')
            replay = service.submit_count(**args)
            check(replay.replayed and row.book_physical_qty == 30, 'Same key/payload -> original result; book remains 30')
            conflict('IDEMPOTENCY_CONFLICT', lambda: service.submit_count(**(args | {'physical_qty': 21})))
            conflict('COUNT_ALREADY_EXISTS', lambda: service.submit_count(**(args | {
                'request_key': 'manual:new-key', 'expected_version': row.version})))
            correction = service.submit_count(**(args | {'physical_qty': 21, 'expected_version': row.version,
                'request_key': 'manual:revision', 'reason': 'Recounted to 21',
                'correction': True, 'expected_count_version': 1}))
            check(correction.physical_delta == 1 and row.book_physical_qty == 31, 'Revision delta=+1 -> current book=31')
            check(db.session.scalar(db.select(db.func.count(InventoryCount.id))) == 1
                and db.session.scalar(db.select(db.func.count(InventoryCountRevision.id))) == 2,
                'One count master, two immutable revisions')
            check(service.get_integrity(store_id=store.id, product_id=row.product_id,
                baseline_at=b, session=db.session).h == 31, 'Usable H=31')
            daily_input(service, negative, actor, b, 25, 'manual:negative')
            blocked = service.get_integrity(store_id=store.id, product_id=negative.product_id,
                baseline_at=b, session=db.session)
            open_tasks = db.session.scalar(db.select(db.func.count(InventoryReconciliation.id)).where(
                InventoryReconciliation.store_id == store.id, InventoryReconciliation.product_id == negative.product_id,
                InventoryReconciliation.status == 'OPEN'))
            check(negative.book_physical_qty == -5 and blocked.h is None and not blocked.usable and open_tasks == 1,
                'Negative book=-5 is preserved, reconciliation OPEN, H=null')
            missing = service.get_integrity(store_id=store.id, product_id=row.product_id,
                baseline_at=b + timedelta(days=1), session=db.session)
            check(missing.missing_dates == ('2026-10-09',) and missing.h is None,
                'Missing daily posting 2026-10-09 -> blocked H=null')
        finally:
            db.session.rollback()
        for table in db.metadata.tables.values():
            check(db.session.scalar(db.select(db.func.count()).select_from(table)) == 0,
                f'Rollback: {table.name} has no test records')
        db.session.rollback()
        print('B01 manual numerical checks complete; no commit or demo changes.')


if __name__ == '__main__':
    run()
