"""Committed test-owned fixtures and independent MySQL connections, never demo."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import and_, func, select, text

from app.extensions import db
from app.models import Order
from app.seed import seed_demo
from app.services.orders import OrderingService
from conftest import login
from test_submission import _prepare, _preview, _submit_body, _write


@pytest.fixture
def committed_app(app, monkeypatch):
    # conftest already validates TEST_DATABASE_URL. Require an empty business
    # database so fixtures cannot overwrite or claim any pre-existing records.
    original = db.engines[None]
    engine = original.engine
    tables = list(db.metadata.tables.values())
    with engine.connect() as connection:
        for table in tables:
            assert connection.scalar(select(func.count()).select_from(table)) == 0, table.name
    db.session.remove()
    db.engines[None] = engine
    monkeypatch.setenv('DEMO_PASSWORD', 'Synthetic-test-password-2026')
    try:
        seed_demo()
        db.session.commit()
        yield app
    finally:
        db.session.remove()
        # Capture exact owned primary keys, including composite association keys.
        # Disable FKs only on this connection to handle circular snapshot links.
        with engine.begin() as connection:
            owned = [(table, list(connection.execute(select(*table.primary_key.columns))))
                     for table in tables]
            connection.execute(text('SET FOREIGN_KEY_CHECKS=0'))
            try:
                for table, keys in owned:
                    for key in keys:
                        connection.execute(table.delete().where(and_(
                            *(column == value for column, value in zip(table.primary_key.columns, key)))))
            finally:
                connection.execute(text('SET FOREIGN_KEY_CHECKS=1'))
        db.engines[None] = original


def race_read_before_lock(monkeypatch):
    original = OrderingService._owned_draft
    barrier = Barrier(2)

    def synchronized(self, draft_id, actor, *, lock=False):
        result = original(self, draft_id, actor, lock=lock)
        if not lock:
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(OrderingService, '_owned_draft', synchronized)


def competing_requests(app, method, url, bodies, keys=None):
    # Login before the barrier is installed; clients have independent sessions.
    clients = [app.test_client(), app.test_client()]
    for client in clients:
        with app.app_context():
            response = login(client)
            assert response.status_code == 200, response.json
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_write, client, method, url, body,
                              {'Idempotency-Key': keys[index]} if keys else None)
                   for index, (client, body) in enumerate(zip(clients, bodies))]
        return [future.result(timeout=20) for future in futures]


def test_two_stale_draft_writers_only_one_succeeds(committed_app, monkeypatch):
    client = committed_app.test_client()
    _, draft = _prepare(committed_app, client)
    bodies = [{'expected_version': draft['version'], 'items': [
        {'product_id': item['product_id'], 'final_qty': qty, 'reason_code': 'promotion'}
        for item in draft['items']]} for qty in (36, 42)]
    db.session.remove()
    race_read_before_lock(monkeypatch)
    results = competing_requests(committed_app, 'PATCH', f"/api/order-drafts/{draft['id']}", bodies)
    assert sorted(response.status_code for response in results) == [200, 409]
    failure = next(response for response in results if response.status_code == 409)
    assert failure.json['error']['code'] == 'VERSION_CONFLICT'


@pytest.mark.parametrize('same_key', [True, False])
def test_simultaneous_submissions_create_exactly_one_order(committed_app, monkeypatch, same_key):
    client = committed_app.test_client()
    _, draft = _prepare(committed_app, client)
    body = _submit_body(draft, _preview(client, draft))
    db.session.remove()
    race_read_before_lock(monkeypatch)
    results = competing_requests(committed_app, 'POST', f"/api/order-drafts/{draft['id']}/submit",
                                [body, body], ['concurrent-a', 'concurrent-a' if same_key else 'concurrent-b'])
    assert sorted(response.status_code for response in results) == ([200, 201] if same_key else [201, 409])
    if same_key:
        assert results[0].json['order_id'] == results[1].json['order_id']
    assert db.session.scalar(select(func.count(Order.id))) == 1
