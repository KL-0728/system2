"""Security, request validation and access to older fulfillment orders."""
import pytest
from flask import g
from app.extensions import db
from app.models import User, Order, OrderItem, OrderDraft
from test_management import admin, login, _write
from test_full_integration import real_order


def test_password_reset_revokes_old_sessions_without_exposing_credentials(seeded, client):
    catalog = admin(client)
    manager = next(u for u in catalog['users'] if u['username'] == 'manager1')
    other = seeded.test_client()
    assert login(other).status_code == 200
    password = 'Replacement-synthetic-password'
    response = _write(client, 'PATCH', f"/api/admin/users/{manager['id']}",
        {**manager, 'password': password})
    assert response.status_code == 200
    assert other.get('/api/auth/me').status_code == 401
    assert login(other).status_code == 401
    assert login(other, password=password).status_code == 200
    g.pop('csrf_token', None)
    serialized = str(client.get('/api/admin/audit').json)
    assert password not in serialized and 'password_hash' not in serialized
    with other.session_transaction() as saved:
        assert saved['credential_token'] != db.session.get(User, manager['id']).password_hash


@pytest.mark.parametrize('query', ['page=bad', 'page=0', 'page=-1', 'page=1000001'])
def test_audit_rejects_invalid_page(seeded, client, query):
    admin(client)
    assert client.get('/api/admin/audit?' + query).status_code == 400


@pytest.mark.parametrize('path', ['orders', 'tasks'])
@pytest.mark.parametrize('value', ['bad', '0', '-1'])
def test_fulfillment_invalid_store_never_falls_back_to_own_store(seeded, client, path, value):
    assert login(client).status_code == 200
    assert client.get(f'/api/fulfillment/{path}?store_id={value}').status_code == 400


def test_older_fulfillment_orders_are_available_and_invalid_fields_do_not_mutate(seeded, client):
    order, item, manager, cycle, run = real_order(seeded, client)
    # Persist minimal older/newer headers in the isolated transaction. These are
    # query fixtures only, never evidence of real submission or fulfillment.
    for index in range(100):
        draft = OrderDraft(store_id=order.store_id, user_id=manager.id,
            cycle_id=cycle.id, run_id=run.run_id, status='SUBMITTED',
            created_at=order.submitted_at, updated_at=order.submitted_at)
        db.session.add(draft)
        db.session.flush()
        db.session.add(Order(store_id=order.store_id, user_id=manager.id,
            cycle_id=cycle.id, draft_id=draft.id, number=f'PAGINATION-{index}', submitted_at=order.submitted_at,
            fixture_only=False))
    db.session.flush()
    first = client.get(f'/api/fulfillment/orders?store_id={order.store_id}').json
    second = client.get(f'/api/fulfillment/orders?store_id={order.store_id}&page=2').json
    assert len(first['orders']) == 100 and first['has_next']
    assert [o['id'] for o in second['orders']] == [order.id] and not second['has_next']
    assert client.get(f'/api/fulfillment/orders?store_id={order.store_id}&page=bad').status_code == 400
    assert login(client, 'operator').status_code == 200
    version = order.version
    url = f'/api/fulfillment/items/{item.id}/accept'
    assert _write(client, 'POST', url, {'expected_version': version}).status_code == 422
    assert _write(client, 'POST', url, {'expected_version': version, 'committed_qty':30,
        'eta': run.protection_end.isoformat(), 'actor_id': manager.id}).status_code == 422
    assert db.session.get(OrderItem, item.id).status == 'SUBMITTED'
    assert db.session.get(Order, order.id).version == version


def test_production_login_hides_demo_instructions(seeded, client):
    seeded.config['APP_ENV'] = 'production'
    page = client.get('/login')
    assert page.status_code == 200
    assert '管理者提供'.encode() in page.data
    assert '本機種子'.encode() not in page.data
    assert '示範時間'.encode() not in page.data
