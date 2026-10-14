"""Regression checks for erroneous inputs, browser recovery and query growth."""
from urllib.parse import parse_qs, urlsplit
from datetime import timedelta
from flask import g
import pytest
from sqlalchemy import event
from app.extensions import db
from app.models import User, Inventory, Product, BusinessClock
from app.services.clock import business_now, round_window, utc_naive
from app.services.inventory import InventoryService
from app.contracts import dto_dict
from test_management import login, _write


def test_ordering_invalid_parameters_never_select_default_store(seeded, client):
    assert login(client).status_code == 200
    paths = ['/store/ordering', '/store/orders', '/api/orders', '/api/stores/current/dashboard',
        '/api/submissions/missing', '/api/orders/1', '/api/orders/1/decision-record']
    for path in paths:
        for query in ['store_id=bad', 'store_id=', 'store_id=0', 'store_id=2147483648',
                'store_id=1&store_id=2', 'store_id=' + '9' * 5000]:
            response = client.get(path + '?' + query)
            assert response.status_code == 400, (path, query[:40], response.json)
    for query in ['page=bad', 'page=0', 'page=-1', 'page=1000001', 'page=1&page=2']:
        assert client.get('/api/orders?' + query).status_code == 400
    assert client.get('/store/ordering?draft_id=bad').status_code == 400
    assert client.get('/api/orders').status_code == 200
    manager = db.session.execute(db.select(User).where(User.username == 'manager2')).scalar_one()
    assert client.get(f'/api/orders?store_id={manager.stores[0].id}').status_code == 404


def test_json_identifiers_and_oversized_product_keys_are_rejected(seeded, client):
    assert login(client).status_code == 200
    for value in [True, [], {}, '1', 0, 2147483648]:
        response = _write(client, 'POST', '/api/order-drafts', {'store_id': value})
        assert response.status_code == 422, response.json
    for key in ['9' * 5000, '0', '2147483648', 'abc']:
        response = _write(client, 'POST', '/api/replenishment/runs', {'modes': {key: 'model'}})
        assert response.status_code == 400, response.json
    assert client.get('/api/inventory/status?store_id=' + '9' * 5000).status_code == 400


def form_login(client, username, password, next_url='/'):
    g.pop('csrf_token', None)
    token = client.get('/api/auth/csrf').json['csrf_token']
    return client.post('/api/auth/login', data={'username': username, 'password': password,
        'csrf_token': token, 'next': next_url})


def test_browser_login_errors_preserve_username_clear_password_and_allow_retry(seeded, client):
    response = form_login(client, 'manager1', 'wrong-secret')
    assert response.status_code == 401 and response.mimetype == 'text/html'
    assert '帳號或密碼錯誤'.encode() in response.data
    assert b'value="manager1"' in response.data and b'wrong-secret' not in response.data
    assert b'role="alert"' in response.data
    assert form_login(client, 'manager1', 'Synthetic-test-password-2026').status_code == 302
    assert client.get('/api/auth/me').status_code == 200
    # Escaping and CSRF rejection must also retain an actionable form.
    response = form_login(client, '<script>alert(1)</script>', 'wrong-secret')
    assert b'<script>alert(1)</script>' not in response.data and b'&lt;script&gt;' in response.data
    response = client.post('/api/auth/login', data={'username': 'manager1', 'password': 'secret'})
    assert response.status_code == 400 and response.mimetype == 'text/html'
    assert b'name="csrf_token"' in response.data and b'value="secret"' not in response.data


def test_browser_reauthentication_returns_to_original_page_and_api_stays_json(seeded, client):
    page = '/store/orders?store_id=1'
    response = client.get(page, headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'})
    assert response.status_code == 302
    assert urlsplit(response.location).path == '/login'
    assert parse_qs(urlsplit(response.location).query)['next'] == [page]
    api = client.get('/api/orders', headers={'Accept': 'text/html'})
    assert api.status_code == 401 and api.is_json
    assert form_login(client, 'manager1', 'Synthetic-test-password-2026', page).location == page
    forbidden = client.get('/admin', headers={'Accept': 'text/html'})
    assert forbidden.status_code == 403 and forbidden.mimetype == 'text/html'
    assert '回首頁'.encode() in forbidden.data


@pytest.mark.parametrize('next_url', ['https://example.com', '//example.com', '/\\example.com',
    '/\n/example.com', 'javascript:alert(1)'])
def test_login_return_url_cannot_redirect_outside_application(seeded, client, next_url):
    response = form_login(client, 'manager1', 'Synthetic-test-password-2026', next_url)
    assert response.status_code == 302 and response.location == '/'


def test_login_page_available_before_demo_clock_initialization(app, client):
    assert db.session.get(BusinessClock, 1) is None
    response = client.get('/login')
    assert response.status_code == 200 and b'name="csrf_token"' in response.data


def test_oversized_login_form_returns_recoverable_413(seeded, client):
    response = client.post('/api/auth/login',
        data='username=' + 'x' * seeded.config['MAX_CONTENT_LENGTH'],
        content_type='application/x-www-form-urlencoded')
    assert response.status_code == 413 and response.mimetype == 'text/html'
    assert b'name="password"' in response.data


def test_inventory_status_preserves_integrity_and_bounds_current_count_queries(seeded, client):
    assert login(client).status_code == 200
    actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    store_id = actor.stores[0].id
    now = round_window(business_now())[0]
    rows = db.session.execute(db.select(Inventory).where(Inventory.store_id == store_id)
        .order_by(Inventory.product_id)).scalars().all()
    rows[0].book_physical_qty = -1
    rows[0].reconciliation_required = True
    rows[1].counted_at = utc_naive(now - timedelta(days=1))
    db.session.flush()
    expected = {row.product_id: seeded.json.loads(seeded.json.dumps(dto_dict(
        InventoryService().get_integrity(store_id=store_id, product_id=row.product_id,
            baseline_at=now, session=db.session)))) for row in rows}
    for index in range(50):
        product = Product(sku=f'AUDIT-{index}', name=f'查詢用商品{index}', pack_size=1)
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(store_id=store_id, product_id=product.id, physical_qty=20,
            book_physical_qty=20, counted_at=utc_naive(now), updated_at=utc_naive(now)))
    db.session.flush()
    statements = []
    engine = db.engine
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        response = client.get('/api/inventory/status')
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.json
    assert len(response.json['items']) == 60
    for item in response.json['items']:
        if item['product_id'] in expected:
            assert all(item[key] == value for key, value in expected[item['product_id']].items())
    assert len(statements) <= 22, len(statements)
    print(f'inventory status: 60 products, {len(statements)} SELECTs')
