"""B02 real MySQL service/API tests; each case rolls back its isolated test transaction."""
import csv
from dataclasses import asdict
from datetime import timedelta
from io import StringIO

import pytest
from sqlalchemy import func
from conftest import login
from test_inventory import concurrent_case

from app.extensions import db
from app.models import (AuditEvent, BusinessClock, Inventory, InventoryCount, InventoryCountRevision,
    InventoryMovement, InventoryReconciliation, Product, SalesDaily, SalesImportBatch, Store, User)
from app.services.clock import aware, business_now, round_window, utc_naive
from app.services.errors import DomainError
from app.services.inventory import InventoryService
from app.services.sales import COLUMNS, SalesService


@pytest.fixture
def sales_case(seeded, client):
    store = db.session.execute(db.select(Store).where(Store.code == 'DEMO1')).scalar_one()
    actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    inventories = db.session.execute(db.select(Inventory).where(Inventory.store_id == store.id)
        .order_by(Inventory.product_id)).scalars().all()
    start = business_now()
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = utc_naive(start + timedelta(days=1, minutes=20))
    db.session.commit()
    assert login(client).status_code == 200
    token = client.get('/api/auth/csrf').json['csrf_token']
    return dict(store=store, actor=actor, rows=inventories, b=start + timedelta(days=1),
        client=client, headers={'X-CSRFToken': token}, service=SalesService())


def csv_text(case, source='sales:first', *, sold=2, day=None, count=1):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    for inventory in case['rows'][:count]:
        product = db.session.get(Product, inventory.product_id)
        writer.writerow([source, case['store'].code, product.sku,
            (day or case['b']).date().isoformat(), sold, 0, 1])
    return stream.getvalue()


def payload(case, **changes):
    data = dict(store_id=case['store'].id, import_mode='daily_posting',
        csv_text=csv_text(case), replaces_batch_id=None, reason='')
    return data | changes


def validated(case, data):
    result = case['client'].post('/api/sales/import/validate', json=data, headers=case['headers'])
    assert result.status_code == 200, result.json
    assert result.json['valid'], result.json
    return {**data, 'validation_token': result.json['validation_token']}


def commit(case, data):
    return case['client'].post('/api/sales/import/commit', json=data, headers=case['headers'])


def count_data(case, **changes):
    row = db.session.get(Inventory, case['rows'][0].id)
    return dict(store_id=case['store'].id, product_id=row.product_id,
        cutoff_at=case['b'].isoformat(), physical_qty=20, unsellable_qty=0,
        expected_version=row.version, request_key='count:first', reason='B02實盤核對') | changes


def count_post(case, data):
    return case['client'].post('/api/inventory/counts', json=data, headers=case['headers'])


def integrity(case, row=None):
    row = row or db.session.get(Inventory, case['rows'][0].id)
    return InventoryService().get_integrity(store_id=case['store'].id, product_id=row.product_id,
        baseline_at=case['b'], session=db.session)


def test_validation_is_read_only_and_post_only_once(sales_case):
    c = sales_case
    before = db.session.scalar(db.select(func.count(SalesImportBatch.id)))
    original_version = c['store'].calculation_version
    prepared = validated(c, payload(c))
    assert db.session.scalar(db.select(func.count(SalesImportBatch.id))) == before
    assert c['store'].calculation_version == original_version
    first = commit(c, prepared)
    assert first.status_code == 201, first.json
    assert first.json['count'] == 1 and first.json['rows'][0]['physical_book'] == 18
    assert integrity(c).usable and integrity(c).h == 18
    replay = commit(c, {**prepared, 'validation_token': 'expired-is-irrelevant-after-success'})
    assert replay.status_code == 200 and replay.json == {**first.json, 'replayed': True}
    assert db.session.scalar(db.select(func.count(InventoryMovement.id))) == 1
    assert c['store'].calculation_version > original_version


def test_historical_does_not_fill_inventory_gap_then_upgrade(sales_case):
    c = sales_case
    history = commit(c, validated(c, payload(c, import_mode='historical')))
    assert history.status_code == 201 and history.json['stock_delta'] == 0
    assert c['rows'][0].book_physical_qty == 20
    assert integrity(c).missing_dates == (c['b'].date().isoformat(),)
    upgrade = payload(c, csv_text=csv_text(c, 'sales:daily'), replaces_batch_id=history.json['batch_id'],
        reason='明確將未入帳歷史區間轉日常')
    daily = commit(c, validated(c, upgrade))
    assert daily.status_code == 201 and daily.json['rows'][0]['physical_book'] == 18
    assert integrity(c).usable
    assert db.session.scalar(db.select(func.count(SalesDaily.id)).where(
        SalesDaily.store_id == c['store'].id, SalesDaily.product_id == c['rows'][0].product_id,
        SalesDaily.business_date == c['b'].date())) == 1


@pytest.mark.parametrize('mode', ['daily_posting', 'historical'])
def test_fresh_batch_cannot_overwrite_existing_interval(sales_case, mode):
    c = sales_case
    commit(c, validated(c, payload(c)))
    result = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text=csv_text(c, 'fresh'), import_mode=mode), headers=c['headers'])
    assert not result.json['valid']
    assert result.json['errors'][0]['code'] == 'SALES_EXISTS'
    assert c['rows'][0].book_physical_qty == 18


@pytest.mark.parametrize('bad,code', [
    ('-1', 'INVALID_QUANTITY'), ('1.5', 'INVALID_QUANTITY'), ('NaN', 'INVALID_QUANTITY'),
    ('1000001', 'INVALID_QUANTITY'), ('true', 'INVALID_QUANTITY'), ('01', 'INVALID_QUANTITY'),
])
def test_bad_quantity_reports_row_and_zero_writes(sales_case, bad, code):
    c = sales_case
    text = csv_text(c, count=2)
    lines = text.splitlines()
    values = lines[2].split(',')
    values[4] = bad
    lines[2] = ','.join(values)
    before = db.session.scalar(db.select(func.count(SalesImportBatch.id)))
    result = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text='\n'.join(lines)), headers=c['headers'])
    assert result.status_code == 200 and not result.json['valid']
    assert result.json['errors'][0]['line'] == 3 and result.json['errors'][0]['code'] == code
    failed = commit(c, payload(c, csv_text='\n'.join(lines), validation_token='invalid'))
    assert failed.status_code == 422
    assert db.session.scalar(db.select(func.count(SalesImportBatch.id))) == before
    assert not db.session.scalar(db.select(func.count(InventoryMovement.id)))


@pytest.mark.parametrize('field,value,code', [
    (1, 'DEMO2', 'STORE_MISMATCH'), (2, 'unknown', 'UNKNOWN_PRODUCT'),
    (3, '2026-10-10', 'FUTURE_SALES'), (3, '2026-2-1', 'INVALID_DATE'),
    (5, 'True', 'INVALID_FLAG'), (6, '0', 'CLOSED_SALES'),
])
def test_row_validation_cases(sales_case, field, value, code):
    c = sales_case
    lines = csv_text(c).splitlines()
    row = lines[1].split(','); row[field] = value; lines[1] = ','.join(row)
    response = c['client'].post('/api/sales/import/validate', json=payload(c,
        csv_text='\n'.join(lines)), headers=c['headers'])
    assert not response.json['valid'] and response.json['errors'][0]['code'] == code


def test_duplicate_rows_and_mixed_sources_rejected(sales_case):
    c = sales_case
    text = csv_text(c)
    response = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text=text + text.splitlines()[1]), headers=c['headers'])
    assert response.json['errors'][0]['code'] == 'DUPLICATE_ROW'
    text = csv_text(c, count=2).replace('sales:first,DEMO1,SKU02', 'other,DEMO1,SKU02')
    response = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text=text), headers=c['headers'])
    assert response.json['errors'][0]['code'] == 'MIXED_BATCH'


@pytest.mark.parametrize('text', [
    '', 'sku,sold_qty\nSKU01,2', ','.join(COLUMNS) + '\n',
    ','.join(COLUMNS) + '\n"unclosed',
])
def test_invalid_csv_structure(sales_case, text):
    c = sales_case
    response = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text=text), headers=c['headers'])
    assert response.status_code == 400 or not response.json['valid']


def test_oversized_csv_and_row_limit(sales_case):
    c = sales_case
    response = c['client'].post('/api/sales/import/validate',
        json=payload(c, csv_text='x' * (512 * 1024 + 1)), headers=c['headers'])
    assert response.status_code == 413
    text = csv_text(c)
    response = c['client'].post('/api/sales/import/validate', json=payload(c,
        csv_text=text + (text.splitlines()[1] + '\n') * 2000), headers=c['headers'])
    assert any(error['code'] == 'CSV_TOO_MANY_ROWS' for error in response.json['errors'])


def test_daily_correction_applies_only_delta_and_history_cannot_evade(sales_case):
    c = sales_case
    first = commit(c, validated(c, payload(c))).json
    correction = payload(c, csv_text=csv_text(c, 'correct', sold=5), replaces_batch_id=first['batch_id'],
        reason='更正已入帳銷售')
    result = commit(c, validated(c, correction))
    assert result.status_code == 201 and result.json['stock_delta'] == -3
    assert c['rows'][0].book_physical_qty == 15 and integrity(c).h == 15
    before = db.session.get(SalesImportBatch, first['batch_id']).snapshot
    assert before['result']['rows'][0]['physical_book'] == 18
    attempted = c['client'].post('/api/sales/import/validate', json=payload(c,
        csv_text=csv_text(c, 'evade', sold=1), import_mode='historical',
        replaces_batch_id=result.json['batch_id'], reason='不能降回歷史'), headers=c['headers'])
    assert attempted.json['errors'][0]['code'] == 'DAILY_MODE_REQUIRED'


def test_negative_book_is_signed_blocks_h_then_correction_resolves(sales_case):
    c = sales_case
    first = commit(c, validated(c, payload(c, csv_text=csv_text(c, sold=25))))
    assert first.status_code == 201 and first.json['rows'][0]['physical_book'] == -5
    state = integrity(c)
    assert not state.usable and state.h is None
    task = db.session.execute(db.select(InventoryReconciliation).where(
        InventoryReconciliation.store_id == c['store'].id)).scalar_one()
    assert task.status == 'OPEN'
    correction = payload(c, csv_text=csv_text(c, 'fix-negative', sold=2),
        replaces_batch_id=first.json['batch_id'], reason='核對錯誤銷售')
    second = commit(c, validated(c, correction))
    assert second.json['stock_delta'] == 23 and integrity(c).h == 18
    db.session.refresh(task)
    assert task.status == 'RESOLVED'


def test_count_delayed_revision_and_retry_api(sales_case):
    c = sales_case
    commit(c, validated(c, payload(c)))
    row = c['rows'][0]
    from app.contracts import InventoryMutation
    writer = InventoryService()
    writer.apply_movement(mutation=InventoryMutation(c['store'].id, row.product_id, 'receipt',
        'B02-controlled-receipt', 10, 0, row.version, c['actor'].id, c['b'] + timedelta(minutes=10),
        'B02受控收貨輸入，非D功能'), session=db.session)
    db.session.commit()
    original = count_data(c)
    first = count_post(c, original)
    assert first.status_code == 201, first.json
    assert first.json['physical_delta'] == 2 and first.json['movement']['physical_book'] == 30
    replay = count_post(c, original)
    assert replay.status_code == 200 and replay.json['replayed']
    conflict = count_post(c, {**original, 'physical_qty': 21})
    assert conflict.status_code == 409 and conflict.json['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    fresh = count_post(c, count_data(c, request_key='count:fresh'))
    assert fresh.status_code == 409 and fresh.json['error']['code'] == 'COUNT_ALREADY_EXISTS'
    revised = count_post(c, count_data(c, physical_qty=21, correction=True, expected_count_version=1,
        request_key='count:revision', reason='核對漏算一件'))
    assert revised.status_code == 201 and revised.json['physical_delta'] == 1
    assert revised.json['movement']['physical_book'] == 31
    assert db.session.scalar(db.select(func.count(InventoryCount.id))) == 1
    assert db.session.scalar(db.select(func.count(InventoryCountRevision.id))) == 2
    assert integrity(c).h == 31


def test_cross_count_correction_creates_task_without_rewriting_book_and_count_resolves(sales_case):
    c = sales_case
    first = commit(c, validated(c, payload(c))).json
    assert count_post(c, count_data(c)).status_code == 201
    correction = payload(c, csv_text=csv_text(c, 'after-count', sold=5),
        replaces_batch_id=first['batch_id'], reason='盤點涵蓋的銷售更正')
    updated = commit(c, validated(c, correction))
    assert updated.status_code == 201 and updated.json['stock_delta'] == 0
    assert c['rows'][0].book_physical_qty == 20
    assert not integrity(c).usable and integrity(c).h is None
    task = db.session.execute(db.select(InventoryReconciliation).where(
        InventoryReconciliation.source_type == 'sales_covered')).scalar_one()
    assert task.status == 'OPEN'
    revision = count_post(c, count_data(c, correction=True, expected_count_version=1,
        request_key='count:reconcile', reason='重新核對實盤'))
    assert revision.status_code == 201 and integrity(c).h == 20
    db.session.refresh(task)
    assert task.status == 'RESOLVED'


def test_checked_seed_history_cannot_be_double_posted(sales_case):
    c = sales_case
    old = db.session.execute(db.select(SalesImportBatch).where(
        SalesImportBatch.store_id == c['store'].id)).scalar_one()
    text = csv_text(c, day=c['b'] - timedelta(days=1), sold=20)
    response = c['client'].post('/api/sales/import/validate', json=payload(c,
        csv_text=text, replaces_batch_id=old.id, reason='不應重扣已核對種子'), headers=c['headers'])
    assert any(error['code'] == 'COUNT_COVERED' for error in response.json['errors'])
    assert c['rows'][0].book_physical_qty == 20


def test_history_correction_before_count_only_forecast_and_reconciliation(sales_case):
    c = sales_case
    day = c['b'] - timedelta(days=20)
    first = commit(c, validated(c, payload(c, import_mode='historical',
        csv_text=csv_text(c, day=day)))).json
    correction = payload(c, import_mode='historical', csv_text=csv_text(c, 'history-fix', day=day, sold=8),
        replaces_batch_id=first['batch_id'], reason='歷史更正')
    result = commit(c, validated(c, correction))
    assert result.status_code == 201 and result.json['stock_delta'] == 0
    assert c['rows'][0].book_physical_qty == 20
    assert db.session.scalar(db.select(func.count(InventoryReconciliation.id))) == 1


def test_correction_must_replace_whole_current_batch(sales_case):
    c = sales_case
    first = commit(c, validated(c, payload(c, csv_text=csv_text(c, count=2)))).json
    partial = payload(c, csv_text=csv_text(c, 'partial'), replaces_batch_id=first['batch_id'], reason='部分不允許')
    response = c['client'].post('/api/sales/import/validate', json=partial, headers=c['headers'])
    assert not response.json['valid']
    assert any(error['code'] == 'CORRECTION_SCOPE' for error in response.json['errors'])


def test_payload_binding_and_version_conflict_and_tampered_token(sales_case):
    c = sales_case
    prepared = validated(c, payload(c))
    mismatch = commit(c, {**prepared, 'csv_text': csv_text(c, sold=3)})
    assert mismatch.status_code == 409 and mismatch.json['error']['code'] == 'VALIDATION_STALE'
    tampered = commit(c, {**prepared, 'validation_token': 'tampered'})
    assert tampered.status_code == 409
    c['store'].calculation_version += 1
    db.session.commit()
    stale = commit(c, prepared)
    assert stale.status_code == 409 and stale.json['error']['code'] == 'VALIDATION_STALE'
    assert not db.session.scalar(db.select(func.count(InventoryMovement.id)))


def test_same_batch_different_content_409_even_after_another_mutation(sales_case):
    c = sales_case
    prepared = validated(c, payload(c))
    assert commit(c, prepared).status_code == 201
    response = commit(c, {**prepared, 'csv_text': csv_text(c, sold=3)})
    assert response.status_code == 409 and response.json['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_route_rolls_back_entire_batch_after_second_writer_failure(sales_case, monkeypatch):
    c = sales_case
    prepared = validated(c, payload(c, csv_text=csv_text(c, count=2)))
    before = db.session.scalar(db.select(func.count(SalesImportBatch.id)))
    original = InventoryService.apply_movement
    calls = []
    def fail_second(self, **kwargs):
        result = original(self, **kwargs)
        calls.append(result)
        if len(calls) == 2:
            raise DomainError('TEST_FAILURE', '測試交易寫後失敗', 409)
        return result
    monkeypatch.setattr(InventoryService, 'apply_movement', fail_second)
    response = commit(c, prepared)
    assert response.status_code == 409
    assert db.session.scalar(db.select(func.count(SalesImportBatch.id))) == before
    assert not db.session.scalar(db.select(func.count(InventoryMovement.id)))
    assert not db.session.scalar(db.select(func.count(AuditEvent.id)))
    assert all(db.session.get(Inventory, row.id).book_physical_qty == 20 for row in c['rows'])
    assert c['store'].calculation_version == 1


@pytest.mark.parametrize('change,code', [
    ({'cutoff_at': '2026-10-09T20:30:00+08:00'}, 'INVALID_COUNT_WINDOW'),
    ({'physical_qty': -1}, 'INVALID_QUANTITY'),
    ({'physical_qty': True}, 'INVALID_QUANTITY'),
    ({'physical_qty': 1, 'unsellable_qty': 2}, 'INVALID_QUANTITY'),
    ({'cutoff_at': '2026-10-09T21:00:00'}, 'INVALID_TIME'),
    ({'expected_version': 1}, 'VERSION_CONFLICT'),
])
def test_count_bad_time_quantity_and_version(sales_case, change, code):
    c = sales_case
    commit(c, validated(c, payload(c)))
    response = count_post(c, count_data(c, **change))
    assert response.status_code in (400, 409, 422)
    assert response.json['error']['code'] == code


def test_history_only_cannot_count_then_effective_count_repairs_negative(sales_case):
    c = sales_case
    response = count_post(c, count_data(c))
    assert response.status_code == 422 and response.json['error']['code'] == 'INVENTORY_GAP'
    commit(c, validated(c, payload(c, csv_text=csv_text(c, sold=25))))
    response = count_post(c, count_data(c, physical_qty=20))
    assert response.status_code == 201 and response.json['physical_delta'] == 25
    assert integrity(c).usable


def test_after_deadline_count_replay_precedes_window(sales_case):
    c = sales_case
    commit(c, validated(c, payload(c)))
    data = count_data(c)
    first = count_post(c, data)
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = utc_naive(c['b'] + timedelta(hours=2))
    db.session.commit()
    replay = count_post(c, data)
    assert replay.status_code == 200 and replay.json == {**first.json, 'replayed': True,
        'movement': {**first.json['movement'], 'replayed': True}}
    fresh = count_post(c, count_data(c, request_key='too-late'))
    assert fresh.status_code == 422 and fresh.json['error']['code'] == 'INVALID_COUNT_WINDOW'


def test_store_isolation_roles_csrf_status_and_page(sales_case):
    c = sales_case
    other = db.session.execute(db.select(Store).where(Store.code == 'DEMO2')).scalar_one()
    assert c['client'].get('/store/data').status_code == 200
    state = c['client'].get('/api/inventory/status').json
    assert state['code'] == 'DEMO1' and state['items'][0]['h'] is None
    assert c['client'].get('/api/inventory/status?store_id=' + str(other.id)).status_code == 404
    assert c['client'].get('/store/data?store_id=' + str(other.id)).status_code == 404
    assert c['client'].get('/store/data?store_id=invalid').status_code == 400
    assert c['client'].post('/api/sales/import/commit', json=payload(c)).status_code == 400
    assert c['client'].post('/api/inventory/counts', json=count_data(c)).status_code == 400
    assert c['client'].post('/api/sales/import/validate', json=payload(c, store_id=other.id),
        headers=c['headers']).status_code == 404
    for username in ('operator', 'admin'):
        assert login(c['client'], username).status_code == 200
        assert c['client'].get('/store/data').status_code == 403
        token = c['client'].get('/api/auth/csrf').json['csrf_token']
        assert c['client'].post('/api/inventory/counts', json=count_data(c),
            headers={'X-CSRFToken': token}).status_code == 403


def test_no_auth_cannot_see_status_or_page(seeded, client):
    assert client.get('/store/data').status_code == 401
    assert client.get('/api/inventory/status').status_code == 401


def test_original_batch_snapshot_is_immutable(sales_case):
    c = sales_case
    result = commit(c, validated(c, payload(c))).json
    batch = db.session.get(SalesImportBatch, result['batch_id'])
    batch.snapshot = {'pending': True}
    with pytest.raises(DomainError, match='銷售原批次'):
        db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize('same_batch', [True, False])
def test_mysql_concurrent_batches_once_or_stale(concurrent_case, same_batch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from app.models import PolicyVersion, StoreProduct
    app, engine, (store_id, product_id, actor_id), b = concurrent_case
    with Session(engine) as session:
        store = session.get(Store, store_id)
        product = session.get(Product, product_id)
        policy = PolicyVersion(store_id=store_id, product_id=product_id, version=1,
            effective_at=utc_naive(b), parameters={})
        session.add(policy)
        session.flush()
        policy_id = policy.id
        link = StoreProduct(store_id=store_id, product_id=product_id, policy_version_id=policy_id,
            lead_days=1, safety_stock=0, capacity=100, active=True)
        session.add(link)
        session.commit()
        store_code, sku, link_id = store.code, product.sku, link.id
    try:
        prepared = []
        for index in range(2):
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(COLUMNS)
            writer.writerow(['concurrent' if same_batch else 'concurrent:' + str(index),
                store_code, sku, b.date().isoformat(), 2, 0, 1])
            data = dict(store_id=store_id, import_mode='daily_posting', csv_text=stream.getvalue())
            with app.app_context(), Session(engine) as session:
                result = SalesService().validate(payload=data, actor_id=actor_id, session=session)
                assert result['valid']
                prepared.append({**data, 'validation_token': result['validation_token']})
                session.commit()
        barrier = Barrier(2)
        def worker(index):
            with app.app_context(), Session(engine) as session:
                barrier.wait(timeout=10)
                data = prepared[index]
                try:
                    result = SalesService().commit(payload=data, actor_id=actor_id,
                        validation_token=data['validation_token'], session=session)
                    session.commit()
                    return result
                except DomainError as error:
                    session.rollback()
                    return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            results = [future.result(timeout=25) for future in futures]
        with Session(engine) as session:
            row = session.execute(db.select(Inventory).where(Inventory.store_id == store_id)).scalar_one()
            assert row.book_physical_qty == 18 and row.version == 2
            assert session.scalar(db.select(func.count(SalesImportBatch.id)).where(
                SalesImportBatch.store_id == store_id)) == 1
            assert session.scalar(db.select(func.count(InventoryMovement.id)).where(
                InventoryMovement.store_id == store_id)) == 1
        if same_batch:
            assert sorted(result['replayed'] for result in results) == [False, True]
            assert results[0]['batch_id'] == results[1]['batch_id']
        else:
            assert sum(result == 'VALIDATION_STALE' for result in results) == 1
    finally:
        # Only the exact B02-added policy/link IDs; B01 fixture removes its own business data.
        with engine.begin() as connection:
            connection.execute(StoreProduct.__table__.delete().where(StoreProduct.id == link_id))
            connection.execute(PolicyVersion.__table__.delete().where(PolicyVersion.id == policy_id))


@pytest.mark.parametrize('bad_token', [None, {}, [], 5])
def test_invalid_token_type_is_controlled_conflict(sales_case, bad_token):
    c = sales_case
    result = commit(c, payload(c, validation_token=bad_token))
    assert result.status_code == 409 and result.json['error']['code'] == 'VALIDATION_EXPIRED'


def test_token_expiry_does_not_use_paused_business_clock(sales_case, monkeypatch):
    from itsdangerous.timed import TimestampSigner
    c = sales_case
    # Freeze only this service scenario; HTTP CSRF/session tokens use real timestamps.
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: 10000)
    data = payload(c)
    validation = c['service'].validate(payload=data, actor_id=c['actor'].id, session=db.session)
    assert validation['valid']
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: 11000)
    with pytest.raises(DomainError) as error:
        c['service'].commit(payload=data, actor_id=c['actor'].id,
            validation_token=validation['validation_token'], session=db.session)
    assert error.value.code == 'VALIDATION_EXPIRED'


def test_multiple_intervals_same_product_zero_sales_and_full_replacement(sales_case):
    c = sales_case
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = utc_naive(c['b'] + timedelta(days=1, minutes=20))
    db.session.commit()
    text = csv_text(c, sold=0) + csv_text(c, sold=3, day=c['b'] + timedelta(days=1)).splitlines()[1] + '\n'
    first = commit(c, validated(c, payload(c, csv_text=text)))
    assert first.status_code == 201 and first.json['stock_delta'] == -3
    assert c['rows'][0].book_physical_qty == 17
    correction_text = csv_text(c, 'multi-correct', sold=2) + csv_text(c, 'multi-correct',
        sold=4, day=c['b'] + timedelta(days=1)).splitlines()[1] + '\n'
    correction = payload(c, csv_text=correction_text, replaces_batch_id=first.json['batch_id'], reason='整批更正兩日')
    second = commit(c, validated(c, correction))
    assert second.status_code == 201 and second.json['stock_delta'] == -3
    assert c['rows'][0].book_physical_qty == 14


def test_invalid_existing_posting_source_cannot_be_corrected_as_real_posting(sales_case):
    c = sales_case
    original = commit(c, validated(c, payload(c))).json
    row = c['rows'][0]
    from app.contracts import InventoryMutation
    receipt = InventoryService().apply_movement(mutation=InventoryMutation(c['store'].id, row.product_id,
        'receipt', 'invalid-sales-link-test', 10, 0, row.version, c['actor'].id, c['b'],
        '合成來源核對'), session=db.session)
    daily = db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id == c['store'].id,
        SalesDaily.business_date == c['b'].date(), SalesDaily.product_id == row.product_id)).scalar_one()
    daily.movement_id = receipt.movement_id  # Deliberately corrupt only a rolled-back test fixture.
    db.session.commit()
    response = c['client'].post('/api/sales/import/validate', json=payload(c,
        csv_text=csv_text(c, 'invalid-source-correction', sold=3),
        replaces_batch_id=original['batch_id'], reason='拒絕把收貨冒充銷售'), headers=c['headers'])
    assert not response.json['valid']
    assert response.json['errors'][0]['code'] == 'INVALID_POSTING_SOURCE'
    assert c['rows'][0].book_physical_qty == 28
