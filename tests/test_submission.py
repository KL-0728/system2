from datetime import timedelta

import pytest

from app.extensions import db
from app.models import Order, OrderConfirmation, OrderItem, Product, Store
from app.providers import register_provider
from app.services.clock import business_now, utc_naive
from app.services.errors import DomainError
from app.testing.factories import make_run
from app.testing.providers import (
    ControlledFulfillment,
    ControlledIntegrity,
    ControlledOpenOrders,
    ControlledRuns,
)
from conftest import login


def _csrf(client):
    return client.get('/api/auth/csrf').json['csrf_token']


def _write(client, method, path, payload, headers=None):
    request_headers = {'X-CSRFToken': _csrf(client)}
    request_headers.update(headers or {})
    return client.open(path, method=method, json=payload, headers=request_headers)


def _prepare(seeded, client, scenario='normal'):
    register_provider('runs', ControlledRuns(scenario), test_only=True)
    register_provider('integrity', ControlledIntegrity(), test_only=True)
    register_provider('open_orders', ControlledOpenOrders(), test_only=True)
    register_provider('fulfillment', ControlledFulfillment(), test_only=True)
    run = make_run(db.session, scenario=scenario)
    db.session.commit()
    assert login(client).status_code == 200
    assert _write(client, 'POST', '/api/ordering/acknowledgement',
        {'acknowledged': True}).status_code == 200
    created = _write(client, 'POST', '/api/order-drafts', {
        'store_id': run.store_id, 'run_id': run.id, 'cycle_id': run.cycle_id})
    assert created.status_code == 201
    return run, created.json


def _save(client, draft, transform=None):
    items = []
    for item in draft['items']:
        value = {'product_id': item['product_id'], 'final_qty': item['final_qty'],
            'reason_code': item['reason_code'], 'reason': item['reason'],
            'special_need': item['special_need'],
            'manual_forecast_acknowledged': item['manual_forecast_acknowledged']}
        items.append(transform(value, item) if transform else value)
    response = _write(client, 'PATCH', f"/api/order-drafts/{draft['id']}", {
        'expected_version': draft['version'], 'items': items})
    assert response.status_code == 200
    return response.json


def _preview(client, draft):
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/preview",
        {'expected_version': draft['version']})
    assert response.status_code == 200
    return response.json


def _submit_body(draft, preview, acknowledgements=None):
    return {'draft_version': draft['version'],
        'confirmation_token': preview['confirmation_token'],
        'order_acknowledged': True,
        'exception_acknowledgements': acknowledgements or []}


def test_atomic_submit_and_idempotent_recovery(seeded, client):
    run, draft = _prepare(seeded, client)
    draft = _save(client, draft)
    preview = _preview(client, draft)
    body = _submit_body(draft, preview)
    key = 'normal-submit-key'
    first = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit", body,
        {'Idempotency-Key': key})
    assert first.status_code == 201
    assert first.json['order_id'] and not first.json['replayed']
    replay = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit", body,
        {'Idempotency-Key': key})
    assert replay.status_code == 200
    assert replay.json['order_id'] == first.json['order_id'] and replay.json['replayed']
    assert db.session.execute(db.select(db.func.count(Order.id))).scalar_one() == 1
    items = db.session.execute(db.select(OrderItem).where(
        OrderItem.order_id == first.json['order_id'])).scalars().all()
    assert len(items) == 10 and {item.original_qty for item in items} == {30}
    result = client.get(f'/api/submissions/{key}?store_id={run.store_id}')
    assert result.status_code == 200 and result.json['order_id'] == first.json['order_id']
    conflict_body = {**body, 'order_acknowledged': False}
    conflict = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit", conflict_body,
        {'Idempotency-Key': key})
    assert conflict.status_code == 409
    assert conflict.json['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_confirmation_expiry_and_store_version_change_block(seeded, client):
    _, draft = _prepare(seeded, client)
    draft = _save(client, draft)
    preview = _preview(client, draft)
    confirmation = db.session.execute(db.select(OrderConfirmation).where(
        OrderConfirmation.draft_id == draft['id'])).scalar_one()
    confirmation.expires_at = utc_naive(business_now() - timedelta(seconds=1))
    db.session.commit()
    expired = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
        _submit_body(draft, preview), {'Idempotency-Key': 'expired-key'})
    assert expired.status_code == 409
    assert expired.json['error']['code'] == 'CONFIRMATION_EXPIRED'

    _, second = _prepare(seeded, client)
    second = _save(client, second)
    second_preview = _preview(client, second)
    store = db.session.get(Store, second['store_id'])
    store.calculation_version += 1
    db.session.commit()
    stale = _write(client, 'POST', f"/api/order-drafts/{second['id']}/submit",
        _submit_body(second, second_preview), {'Idempotency-Key': 'stale-key'})
    assert stale.status_code == 409
    assert stale.json['error']['code'] == 'VERSION_CONFLICT'


def test_original_quantity_is_immutable_after_submission(seeded, client):
    _, draft = _prepare(seeded, client)
    draft = _save(client, draft)
    preview = _preview(client, draft)
    submitted = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
        _submit_body(draft, preview), {'Idempotency-Key': 'immutable-key'})
    assert submitted.status_code == 201
    item = db.session.execute(db.select(OrderItem).where(
        OrderItem.order_id == submitted.json['order_id'])).scalars().first()
    item.original_qty += 1
    with pytest.raises(DomainError) as error:
        db.session.flush()
    assert error.value.code == 'IMMUTABLE_RECORD'
    db.session.rollback()


def test_direct_special_order_keeps_null_model_and_requires_item_ack(seeded, client):
    run, draft = _prepare(seeded, client, scenario='direct')
    products = {row.id: row for row in db.session.execute(db.select(Product)).scalars()}

    def direct(value, original):
        product = products[value['product_id']]
        value.update(final_qty=1000 if product.name == '雨衣' else product.pack_size,
            reason_code='local_demand', reason='週六社區活動特殊需求，已確認數量與收貨安排',
            special_need={'need_date': '2026-10-10', 'need_qty': 1000 if product.name == '雨衣' else product.pack_size,
                'arrangement': '到貨後直接交付活動單位', 'reason': '週六社區活動特殊需求'})
        return value

    draft = _save(client, draft, direct)
    preview = _preview(client, draft)
    raincoat = next(item for item in preview['snapshot']['items'] if item['name'] == '雨衣')
    assert raincoat['mode'] == 'direct'
    assert raincoat['mu'] is None and raincoat['suggested_qty'] is None
    assert {'DIRECT_ORDER', 'LARGE_QUANTITY', 'CAPACITY'} <= set(raincoat['important_codes'])
    missing = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
        _submit_body(draft, preview), {'Idempotency-Key': 'direct-missing-ack'})
    assert missing.status_code == 422
    acknowledgements = [{'product_id': product_id, 'warning_version': '1',
        'acknowledged': True, 'handling': 'special_arrangement',
        'reason': '已核對特殊需求與收貨安排'}
        for product_id in preview['snapshot']['important_product_ids']]
    submitted = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
        _submit_body(draft, preview, acknowledgements),
        {'Idempotency-Key': 'direct-complete-ack'})
    assert submitted.status_code == 201
    detail = client.get(f"/api/orders/{submitted.json['order_id']}?store_id={run.store_id}")
    assert detail.status_code == 200
    assert detail.json['fulfillment']['items'][0]['source'] == 'controlled-fulfillment'
