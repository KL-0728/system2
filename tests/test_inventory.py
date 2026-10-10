"""B01 real MySQL accounting tests; never reset demo or use a writer double."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta, time
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import InventoryMutation
from app.extensions import db
from app.models import (AuditEvent, BusinessClock, CountSubmissionKey, Inventory, InventoryCount,
    InventoryCountRevision, InventoryMovement, InventoryReconciliation, Product,
    SalesDaily, SalesImportBatch, Store, User)
from app.providers import get_provider
from app.services.clock import aware, business_now, utc_naive
from app.services.errors import DomainError
from app.services.inventory import InventoryService



@pytest.fixture
def case(seeded):
    store = db.session.execute(select(Store).where(Store.code == 'DEMO1')).scalar_one()
    actor = db.session.execute(select(User).where(User.username == 'manager1')).scalar_one()
    inventory = db.session.execute(select(Inventory).where(Inventory.store_id == store.id)
        .order_by(Inventory.product_id)).scalars().first()
    return InventoryService(), store, actor, inventory, business_now()


def move(case, *, source='receipt', key='receipt:1', physical=10, damaged=0, at=None, version=None):
    service, store, actor, row, b = case
    mutation = InventoryMutation(store.id, row.product_id, source, key, physical, damaged,
        row.version if version is None else version, actor.id, at or business_now(), 'B01合成測試')
    return mutation, service.apply_movement(mutation=mutation, session=db.session)


def advance(b, minutes=20, days=0):
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = utc_naive(b + timedelta(days=days, minutes=minutes))
    db.session.flush()


def post_daily(case, *, cutoff=None, sold=2, key='sales:day'):
    # Real persisted sales inputs for B01 validation, not a claim of B02 CSV support.
    service, store, actor, row, b = case
    cutoff = cutoff or b
    # Prepare a synthetic prior-day count, so this daily interval is not
    # already covered by A03's explicitly checked seed baseline.
    if row.counted_at == utc_naive(cutoff):
        row.counted_at = utc_naive(cutoff - timedelta(days=1))
        db.session.flush()
    mutation, result = move(case, source='sales', key=key, physical=-sold, at=cutoff)
    daily = db.session.execute(select(SalesDaily).where(SalesDaily.store_id == store.id,
        SalesDaily.product_id == row.product_id, SalesDaily.business_date == cutoff.date())
    ).scalar_one_or_none()
    batch = SalesImportBatch(store_id=store.id, source_batch_id=key, payload_hash='1' * 64,
        import_mode='daily_posting', actor_id=actor.id, created_at=utc_naive(business_now()), snapshot={'synthetic': True})
    db.session.add(batch)
    db.session.flush()
    if daily is None:
        daily = SalesDaily(store_id=store.id, product_id=row.product_id, business_date=cutoff.date(),
            interval_start=utc_naive(cutoff - timedelta(days=1)), interval_end=utc_naive(cutoff),
            sold_qty=sold, was_stockout=False, is_open=True, batch_id=batch.id, import_mode='daily_posting')
        db.session.add(daily)
    daily.batch_id, daily.import_mode, daily.sold_qty = batch.id, 'daily_posting', sold
    daily.applied_at, daily.movement_id = utc_naive(business_now()), result.movement_id
    db.session.flush()
    return daily


def count_args(case, **changes):
    service, store, actor, row, b = case
    args = dict(store_id=store.id, product_id=row.product_id, actor_id=actor.id, cutoff_at=b,
        physical_qty=20, unsellable_qty=0, expected_version=row.version,
        request_key='count:first', reason='B01合成實盤核對', session=db.session)
    return args | changes


def error(code, call):
    with pytest.raises(DomainError) as exc:
        call()
    assert exc.value.code == code
    return exc.value


def test_real_providers_registered_without_test_mode(case):
    assert isinstance(get_provider('inventory_writer'), InventoryService)
    assert isinstance(get_provider('integrity'), InventoryService)


def test_receipt_damaged_h_and_original_result_replay(case):
    service, store, actor, row, b = case
    mutation, original = move(case, physical=12, damaged=2)
    assert (original.physical_book, original.unsellable_book, row.physical_qty) == (32, 2, 20)
    assert (row.version, store.calculation_version) == (2, 2)
    integrity = service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session)
    assert integrity.usable and integrity.h == 30
    move(case, key='receipt:2', physical=3)
    replay = service.apply_movement(mutation=mutation, session=db.session)
    assert replay == replace(original, replayed=True)
    assert row.book_physical_qty == 35 and row.version == 3 and store.calculation_version == 3
    assert db.session.scalar(select(func.count(InventoryMovement.id))) == 2


@pytest.mark.parametrize('changes', [
    {'physical_delta': 11}, {'unsellable_delta': 1}, {'reason': '另一理由'},
    {'occurred_at': None}, {'actor_id': None}, {'expected_version': 2}, {'source_id': 'RECEIPT:1'},
])
def test_same_source_changed_content_conflicts(case, changes):
    service, store, actor, row, b = case
    mutation, _ = move(case)
    if 'occurred_at' in changes:
        changes['occurred_at'] = b - timedelta(seconds=1)
    if 'actor_id' in changes:
        changes['actor_id'] = db.session.execute(select(User.id).where(User.username == 'admin')).scalar_one()
    exc = error('IDEMPOTENCY_CONFLICT',
        lambda: service.apply_movement(mutation=replace(mutation, **changes), session=db.session))
    assert exc.status == 409 and row.book_physical_qty == 30 and row.version == 2


def test_stale_version_authorization_and_invalid_time_no_write(case):
    service, store, actor, row, b = case
    mutation, _ = move(case)
    error('VERSION_CONFLICT', lambda: service.apply_movement(
        mutation=replace(mutation, source_id='new-source', expected_version=1), session=db.session))
    other = db.session.execute(select(User).where(User.username == 'manager2')).scalar_one()
    error('NOT_FOUND', lambda: service.apply_movement(
        mutation=replace(mutation, actor_id=other.id), session=db.session))
    error('INVALID_TIME', lambda: service.apply_movement(
        mutation=replace(mutation, source_id='future', expected_version=row.version,
            occurred_at=b + timedelta(seconds=1)), session=db.session))
    assert row.book_physical_qty == 30 and db.session.scalar(select(func.count(InventoryMovement.id))) == 1


@pytest.mark.parametrize('physical,damaged', [(-21, 0), (0, -1), (0, 21)])
def test_invalid_non_sales_book_rejected(case, physical, damaged):
    error('INVALID_QUANTITY', lambda: move(case, physical=physical, damaged=damaged))
    assert case[3].book_physical_qty == 20


def test_writer_and_count_rollback_with_outer_transaction(case):
    service, store, actor, row, b = case
    savepoint = db.session.begin_nested()
    _, result = move(case)
    # Caller failure after B flush must roll back stock, source, version and audit.
    assert result.physical_book == 30
    savepoint.rollback()
    db.session.expire_all()
    assert row.book_physical_qty == 20 and row.version == 1 and store.calculation_version == 1
    assert db.session.scalar(select(func.count(InventoryMovement.id))) == 0
    assert db.session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == 'inventory.apply')) == 0
    post_daily(case)
    args = count_args(case)
    savepoint = db.session.begin_nested()
    service.submit_count(**args)
    savepoint.rollback()
    db.session.expire_all()
    assert row.book_physical_qty == 18 and row.version == 2
    assert db.session.scalar(select(func.count(InventoryCount.id))) == 0
    assert db.session.scalar(select(func.count(CountSubmissionKey.id))) == 0
    # Rolled-back key is retryable.
    assert service.submit_count(**args).movement.physical_book == 20


@pytest.mark.parametrize('sold,physical,unsellable,expected_delta,expected_book', [
    (0, 20, 0, 0, 30), (2, 20, 0, 2, 30), (2, 20, 2, 2, 30),
])
def test_delayed_count_preserves_later_receipt(case, sold, physical, unsellable, expected_delta, expected_book):
    service, store, actor, row, b = case
    post_daily(case, sold=sold)
    advance(b, 10)
    move(case, at=b + timedelta(minutes=10), physical=10)
    advance(b, 20)
    result = service.submit_count(**count_args(case, physical_qty=physical, unsellable_qty=unsellable))
    assert result.physical_delta == expected_delta and result.unsellable_delta == unsellable
    assert result.movement.physical_book == expected_book
    assert row.physical_qty == physical and row.book_physical_qty == expected_book
    assert row.book_unsellable_qty == unsellable
    count = db.session.get(InventoryCount, result.count_id)
    assert count.baseline_physical_qty == 20 - sold
    assert row.counted_at == utc_naive(b)


def test_count_retry_revision_and_unique_main_record(case):
    service, store, actor, row, b = case
    post_daily(case)
    advance(b, 10)
    move(case, physical=10)
    advance(b, 20)
    args = count_args(case)
    first = service.submit_count(**args)
    assert first.physical_delta == 2 and row.book_physical_qty == 30
    assert service.submit_count(**args).movement == replace(first.movement, replayed=True)
    error('IDEMPOTENCY_CONFLICT', lambda: service.submit_count(**(args | {'physical_qty': 21})))
    error('COUNT_ALREADY_EXISTS', lambda: service.submit_count(**count_args(case, request_key='count:new')))
    error('VERSION_CONFLICT', lambda: service.submit_count(**count_args(case, request_key='count:stale',
        correction=True, expected_count_version=2)))
    revision_args = count_args(case, physical_qty=21, request_key='count:revision',
        correction=True, expected_count_version=1, reason='重數後修正為21件')
    second = service.submit_count(**revision_args)
    assert second.revision == 2 and second.physical_delta == 1 and row.book_physical_qty == 31
    assert db.session.scalar(select(func.count(InventoryCount.id))) == 1
    assert db.session.scalar(select(func.count(InventoryCountRevision.id))) == 2
    assert db.session.get(InventoryCountRevision, first.revision_id).physical_qty == 20
    move(case, key='receipt:later', physical=4)
    advance(b, 70)
    # Success retries take precedence over cutoff/stale versions and later mutations.
    replay = service.submit_count(**args)
    assert replay.movement.physical_book == 30 and replay.revision == 1 and replay.replayed
    assert service.submit_count(**revision_args).movement.physical_book == 31
    assert row.book_physical_qty == 35


@pytest.mark.parametrize('changes,code', [
    ({'cutoff_at': 'early'}, 'INVALID_COUNT_WINDOW'),
    ({'physical_qty': -1}, 'INVALID_QUANTITY'),
    ({'physical_qty': True}, 'INVALID_QUANTITY'),
    ({'unsellable_qty': 21}, 'INVALID_QUANTITY'),
    ({'reason': ' '}, 'INVALID_INPUT'),
    ({'correction': True}, 'INVALID_QUANTITY'),
])
def test_count_validation(case, changes, code):
    post_daily(case)
    if changes.get('cutoff_at') == 'early':
        changes['cutoff_at'] = case[4] - timedelta(minutes=30)
    error(code, lambda: case[0].submit_count(**count_args(case, **changes)))
    assert db.session.scalar(select(func.count(InventoryCount.id))) == 0


def test_count_requires_current_daily_posting_and_manager(case):
    service, store, actor, row, b = case
    error('INVENTORY_GAP', lambda: service.submit_count(**count_args(case)))
    post_daily(case)
    daily = db.session.execute(select(SalesDaily).where(SalesDaily.store_id == store.id,
        SalesDaily.product_id == row.product_id, SalesDaily.business_date == b.date())).scalar_one()
    daily.interval_start -= timedelta(minutes=1)
    db.session.flush()
    error('INVENTORY_GAP', lambda: service.submit_count(**count_args(case)))
    daily.interval_start += timedelta(minutes=1)
    operator = db.session.execute(select(User).where(User.username == 'operator')).scalar_one()
    error('FORBIDDEN', lambda: service.submit_count(**count_args(case, actor_id=operator.id)))
    daily.import_mode = 'daily_posting'
    advance(b, 60)
    error('INVALID_COUNT_WINDOW', lambda: service.submit_count(**count_args(case)))


def test_negative_sales_preserved_blocked_and_count_resolves(case):
    service, store, actor, row, b = case
    post_daily(case, sold=25)
    assert row.book_physical_qty == -5 and row.physical_qty == 20 and row.reconciliation_required
    integrity = service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session)
    assert not integrity.usable and integrity.h is None and integrity.warnings[0].code == 'NEGATIVE_BOOK'
    task = db.session.execute(select(InventoryReconciliation)).scalar_one()
    assert task.status == 'OPEN'
    result = service.submit_count(**count_args(case, physical_qty=1, reason='實盤核對後修正'))
    assert result.physical_delta == 6 and row.book_physical_qty == 1
    assert not row.reconciliation_required and task.status == 'RESOLVED'
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).h == 1
    assert db.session.get(InventoryMovement, result.movement.movement_id).physical_delta == 6


def test_integrity_contiguous_posting_historical_not_posted_and_forged_source(case):
    service, store, actor, row, b = case
    # Seed's explicitly verified baseline needs no invented pre-baseline postings.
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).h == 20
    row.counted_at = utc_naive(b - timedelta(days=2))
    db.session.flush()
    missing = service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session)
    assert missing.missing_dates == ('2026-10-07', '2026-10-08') and missing.h is None
    first = post_daily(case, cutoff=b - timedelta(days=1), key='sales:yesterday')
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).missing_dates == ('2026-10-08',)
    second = post_daily(case)
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).h == 16
    _, receipt = move(case, key='forged-reference')
    second.movement_id = receipt.movement_id
    db.session.flush()
    assert not service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).usable
    second.movement_id = None
    first.import_mode = 'historical'
    db.session.flush()
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).missing_dates == ('2026-10-07', '2026-10-08')


@pytest.mark.parametrize('offset', [timedelta(minutes=-30), timedelta(days=1)])
def test_invalid_or_future_count_baseline_has_no_h(case, offset):
    service, store, actor, row, b = case
    row.counted_at = utc_naive(b + offset)
    result = service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session)
    assert result.baseline_counted_at is None and result.h is None


def test_immutable_count_revision_and_movement(case):
    service = case[0]
    post_daily(case)
    result = service.submit_count(**count_args(case))
    for model, identity, field in (
        (InventoryCount, result.count_id, 'baseline_physical_qty'),
        (InventoryCountRevision, result.revision_id, 'physical_qty'),
        (InventoryMovement, result.movement.movement_id, 'physical_delta'),
    ):
        savepoint = db.session.begin_nested()
        record = db.session.get(model, identity)
        setattr(record, field, 99)
        error('IMMUTABLE_RECORD', lambda: db.session.flush())
        savepoint.rollback()


@pytest.fixture
def concurrent_case(app):
    # Independent connections need committed fixtures. Require the configured
    # local test DB to be empty, then delete only exact test-owned primary keys.
    engine = db.engine.engine
    with engine.connect() as connection:
        for table in db.metadata.tables.values():
            assert connection.scalar(select(func.count()).select_from(table)) == 0, table.name
    with Session(engine) as session, session.begin():
        actor = User(username='B01-' + uuid4().hex[:12], role='manager', active=True, password_hash='test-only')
        store = Store(code='B01-' + uuid4().hex[:12], name='B01併發測試', cutoff=time(22), active=True)
        product = Product(sku='B01-' + uuid4().hex[:12], name='B01測試商品', base_unit='件', pack_size=1, active=True)
        actor.stores.append(store)
        session.add_all((actor, store, product))
        session.flush()
        from datetime import datetime, timezone
        b = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
        session.add(BusinessClock(id=1, business_anchor=utc_naive(b), server_anchor=utc_naive(b), paused=True))
        session.add(Inventory(store_id=store.id, product_id=product.id, physical_qty=20, unsellable_qty=0,
            book_physical_qty=20, book_unsellable_qty=0, counted_at=utc_naive(b - timedelta(days=1)), updated_at=utc_naive(b)))
        ids = store.id, product.id, actor.id
    try:
        yield app, engine, ids, b
    finally:
        db.session.remove()
        # These are all B01-owned rows, with no unrelated fixture data or FK disabling.
        _cleanup_owned(engine, ids)


def _cleanup_owned(engine, ids):
    store_id, product_id, actor_id = ids
    with engine.begin() as connection:
        revision_ids = list(connection.scalars(select(InventoryCountRevision.id).join(InventoryCount,
            InventoryCountRevision.count_id == InventoryCount.id).where(InventoryCount.store_id == store_id)))
        connection.execute(CountSubmissionKey.__table__.delete().where(CountSubmissionKey.store_id == store_id))
        if revision_ids:
            connection.execute(InventoryCountRevision.__table__.delete().where(InventoryCountRevision.id.in_(revision_ids)))
        for model in (SalesDaily, SalesImportBatch, InventoryReconciliation, AuditEvent,
                InventoryMovement, InventoryCount, Inventory):
            connection.execute(model.__table__.delete().where(model.store_id == store_id))
        association = db.metadata.tables['user_stores']
        connection.execute(association.delete().where(association.c.user_id == actor_id))
        for model, identity in ((BusinessClock, 1), (User, actor_id), (Product, product_id), (Store, store_id)):
            connection.execute(model.__table__.delete().where(model.id == identity))



@pytest.mark.parametrize('same_source', [True, False])
def test_mysql_simultaneous_writers_serialize_and_source_is_unique(concurrent_case, same_source):
    application, engine, (store_id, product_id, actor_id), b = concurrent_case
    barrier = Barrier(2)
    def worker(index):
        with application.app_context(), Session(engine) as session:
            # Read before lock to prove stale identity-map state is refreshed.
            session.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
            barrier.wait(timeout=10)
            mutation = InventoryMutation(store_id, product_id, 'receipt',
                'same' if same_source else f'different:{index}', 10, 0, 1, actor_id, b, 'B01並行測試')
            try:
                result = InventoryService().apply_movement(mutation=mutation, session=session)
                session.commit()
                return result
            except DomainError as exc:
                session.rollback()
                return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        results = [future.result(timeout=20) for future in futures]
    with Session(engine) as session:
        row = session.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
        assert row.book_physical_qty == 30 and row.version == 2
        assert session.get(Store, store_id).calculation_version == 2
        assert session.scalar(select(func.count(InventoryMovement.id))) == 1
    if same_source:
        assert sorted(result.replayed for result in results) == [False, True]
        assert results[0].movement_id == results[1].movement_id
    else:
        assert sum(result == 'VERSION_CONFLICT' for result in results) == 1


def test_later_receipt_cannot_silently_clear_negative_reconciliation(case):
    service, store, actor, row, b = case
    post_daily(case, sold=25)
    advance(b, 10)
    move(case, physical=10)
    integrity = service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session)
    assert row.book_physical_qty == 5 and row.reconciliation_required
    assert integrity.h is None and not integrity.usable
    assert any(w.code == 'NEGATIVE_BOOK' for w in integrity.warnings)
    service.submit_count(**count_args(case, physical_qty=0, reason='核對銷售與實盤後修正'))
    assert row.book_physical_qty == 10 and not row.reconciliation_required
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).h == 10


@pytest.mark.parametrize('mode', ['same_key', 'different_key', 'revision'])
def test_mysql_count_submission_and_revision_races(concurrent_case, mode):
    application, engine, (store_id, product_id, actor_id), b = concurrent_case
    with Session(engine) as session, application.app_context():
        service = InventoryService()
        movement = service.apply_movement(mutation=InventoryMutation(store_id, product_id,
            'sales', 'daily-zero', 0, 0, 1, actor_id, b, 'B01零銷售入帳'), session=session)
        batch = SalesImportBatch(store_id=store_id, source_batch_id='B01-race', payload_hash='0' * 64,
            import_mode='daily_posting', actor_id=actor_id, created_at=utc_naive(b), snapshot={'synthetic': True})
        session.add(batch)
        session.flush()
        session.add(SalesDaily(store_id=store_id, product_id=product_id, business_date=b.date(),
            interval_start=utc_naive(b - timedelta(days=1)), interval_end=utc_naive(b), sold_qty=0,
            was_stockout=False, is_open=True, batch_id=batch.id, import_mode='daily_posting',
            applied_at=utc_naive(b), movement_id=movement.movement_id))
        session.flush()
        version = 2
        if mode == 'revision':
            service.submit_count(store_id=store_id, product_id=product_id, actor_id=actor_id, cutoff_at=b,
                physical_qty=20, unsellable_qty=0, expected_version=2, request_key='original',
                reason='原始盤點', session=session)
            version = 3
        session.commit()
    barrier = Barrier(2)
    def worker(index):
        with application.app_context(), Session(engine) as session:
            session.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
            barrier.wait(timeout=10)
            try:
                result = InventoryService().submit_count(store_id=store_id, product_id=product_id,
                    actor_id=actor_id, cutoff_at=b, physical_qty=21 if mode == 'revision' else 20,
                    unsellable_qty=0, expected_version=version, request_key='same' if mode == 'same_key' else f'key:{index}',
                    reason='B01競爭盤點', session=session, correction=mode == 'revision',
                    expected_count_version=1 if mode == 'revision' else None)
                session.commit()
                return result
            except DomainError as exc:
                session.rollback()
                return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        results = [future.result(timeout=20) for future in futures]
    with Session(engine) as session:
        assert session.scalar(select(func.count(InventoryCount.id))) == 1
        assert session.scalar(select(func.count(InventoryCountRevision.id))) == (2 if mode == 'revision' else 1)
        row = session.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
        assert row.book_physical_qty == (21 if mode == 'revision' else 20)
    if mode == 'same_key':
        assert sorted(result.replayed for result in results) == [False, True]
        assert results[0].revision_id == results[1].revision_id
    else:
        assert sum(result == 'VERSION_CONFLICT' for result in results) == 1

def test_damaged_receipt_and_count_revision_preserve_both_book_components(case):
    service, store, actor, row, b = case
    post_daily(case)
    advance(b, 10)
    move(case, physical=10, damaged=3)
    advance(b, 20)
    first = service.submit_count(**count_args(case, unsellable_qty=1))
    assert (first.physical_delta, first.unsellable_delta) == (2, 1)
    assert (row.book_physical_qty, row.book_unsellable_qty) == (30, 4)
    second = service.submit_count(**count_args(case, physical_qty=21, unsellable_qty=2,
        request_key='damaged:revision', correction=True, expected_count_version=1, reason='實盤兩者修正'))
    assert (second.physical_delta, second.unsellable_delta) == (1, 1)
    assert (row.book_physical_qty, row.book_unsellable_qty, row.physical_qty, row.unsellable_qty) == (31, 5, 21, 2)
    assert service.get_integrity(store_id=store.id, product_id=row.product_id, baseline_at=b, session=db.session).h == 26


def test_source_identity_is_scoped_to_store_and_product(case):
    service, store, actor, row, b = case
    original, first = move(case)
    other_product = db.session.execute(select(Inventory).where(Inventory.store_id == store.id,
        Inventory.product_id != row.product_id).order_by(Inventory.product_id)).scalars().first()
    second = service.apply_movement(mutation=replace(original, product_id=other_product.product_id), session=db.session)
    other_store = db.session.execute(select(Store).where(Store.code == 'DEMO2')).scalar_one()
    admin = db.session.execute(select(User).where(User.username == 'admin')).scalar_one()
    third = service.apply_movement(mutation=replace(original, store_id=other_store.id, actor_id=admin.id), session=db.session)
    assert len({first.movement_id, second.movement_id, third.movement_id}) == 3
    assert [first.physical_book, second.physical_book, third.physical_book] == [30, 30, 30]
    assert (store.calculation_version, other_store.calculation_version) == (3, 2)


def test_independent_caller_rollback_keeps_committed_stock_unchanged(concurrent_case):
    application, engine, (store_id, product_id, actor_id), b = concurrent_case
    with application.app_context(), Session(engine) as session:
        result = InventoryService().apply_movement(mutation=InventoryMutation(store_id, product_id,
            'receipt', 'rolled-back', 10, 0, 1, actor_id, b, '呼叫端稍後失敗'), session=session)
        assert result.physical_book == 30
        session.rollback()
    with Session(engine) as session:
        row = session.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
        assert row.book_physical_qty == 20 and row.version == 1
        assert session.get(Store, store_id).calculation_version == 1
        assert session.scalar(select(func.count(InventoryMovement.id))) == 0
        assert session.scalar(select(func.count(AuditEvent.id))) == 0


@pytest.mark.parametrize('kind', ['late_receipt', 'stale_count'])
def test_count_current_reads_after_an_earlier_repeatable_read_snapshot(concurrent_case, kind):
    application, engine, (store_id, product_id, actor_id), b = concurrent_case
    with application.app_context(), Session(engine) as session:
        service = InventoryService()
        posted = service.apply_movement(mutation=InventoryMutation(store_id, product_id,
            'sales', 'snapshot:daily', 0, 0, 1, actor_id, b, '零銷售入帳'), session=session)
        batch = SalesImportBatch(store_id=store_id, source_batch_id='snapshot:batch', payload_hash='0' * 64,
            import_mode='daily_posting', actor_id=actor_id, created_at=utc_naive(b), snapshot={'synthetic': True})
        session.add(batch)
        session.flush()
        session.add(SalesDaily(store_id=store_id, product_id=product_id, business_date=b.date(),
            interval_start=utc_naive(b - timedelta(days=1)), interval_end=utc_naive(b), sold_qty=0,
            was_stockout=False, is_open=True, batch_id=batch.id, import_mode='daily_posting',
            applied_at=utc_naive(b), movement_id=posted.movement_id))
        clock = session.get(BusinessClock, 1)
        clock.business_anchor = utc_naive(b + timedelta(minutes=20))
        session.flush()
        if kind == 'stale_count':
            service.submit_count(store_id=store_id, product_id=product_id, actor_id=actor_id,
                cutoff_at=b, physical_qty=20, unsellable_qty=0, expected_version=2,
                request_key='snapshot:first', reason='初次核對', session=session)
        session.commit()
    with application.app_context(), Session(engine) as stale:
        old = stale.execute(select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
        assert old.book_physical_qty == 20 and old.version == (3 if kind == 'stale_count' else 2)
        if kind == 'stale_count':
            old_count = stale.execute(select(InventoryCount).where(InventoryCount.store_id == store_id)).scalar_one()
            assert old_count.version == 1
        with Session(engine) as other:
            service = InventoryService()
            if kind == 'stale_count':
                service.submit_count(store_id=store_id, product_id=product_id, actor_id=actor_id,
                    cutoff_at=b, physical_qty=21, unsellable_qty=0, expected_version=3,
                    request_key='snapshot:other-revision', reason='另一交易修訂',
                    correction=True, expected_count_version=1, session=other)
            else:
                service.apply_movement(mutation=InventoryMutation(store_id, product_id,
                    'receipt', 'snapshot:receipt', 10, 0, 2, actor_id, b + timedelta(minutes=10),
                    '另一交易已入帳的截止後收貨'), session=other)
            other.commit()
        # Simulate C's outer store lock while Inventory is still cached from an
        # earlier read. Integrity must return the current book and source state.
        locked_store = stale.execute(select(Store).where(Store.id == store_id)
            .execution_options(populate_existing=True).with_for_update()).scalar_one()
        integrity = InventoryService().get_integrity(store_id=store_id, product_id=product_id,
            baseline_at=b, session=stale)
        assert integrity.h == (21 if kind == 'stale_count' else 30)
        assert integrity.inventory_version == integrity.store_version == locked_store.calculation_version
        args = dict(store_id=store_id, product_id=product_id, actor_id=actor_id,
            cutoff_at=b, physical_qty=20, unsellable_qty=0, expected_version=3, request_key='snapshot:count',
            reason='核對新版本後提交實盤', session=stale)
        if kind == 'stale_count':
            args.update(expected_version=4, correction=True, expected_count_version=1, physical_qty=22)
            error('VERSION_CONFLICT', lambda: InventoryService().submit_count(**args))
            stale.rollback()
            assert old_count.version == 2
            assert stale.scalar(select(func.count(InventoryCountRevision.id))) == 2
        else:
            result = InventoryService().submit_count(**args)
            assert result.physical_delta == 0 and result.movement.physical_book == 30
            stale.commit()


def test_count_key_and_master_cannot_be_deleted_or_rewritten(case):
    service = case[0]
    post_daily(case)
    result = service.submit_count(**count_args(case))
    key = db.session.execute(select(CountSubmissionKey)).scalar_one()
    savepoint = db.session.begin_nested()
    key.payload_hash = 'x' * 64
    error('IMMUTABLE_RECORD', lambda: db.session.flush())
    savepoint.rollback()
    for record in (db.session.get(CountSubmissionKey, key.id), db.session.get(InventoryCount, result.count_id)):
        savepoint = db.session.begin_nested()
        db.session.delete(record)
        error('IMMUTABLE_RECORD', lambda: db.session.flush())
        savepoint.rollback()
