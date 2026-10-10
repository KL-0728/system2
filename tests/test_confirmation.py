from datetime import timedelta

from app.extensions import db
from app.models import DraftItem, OrderDraft, Store, UserAcknowledgement
from app.providers import register_provider
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


def _providers(scenario='normal'):
    register_provider('runs', ControlledRuns(scenario), test_only=True)
    register_provider('integrity', ControlledIntegrity(), test_only=True)
    register_provider('open_orders', ControlledOpenOrders(), test_only=True)
    register_provider('fulfillment', ControlledFulfillment(), test_only=True)


def _acknowledge(client):
    response = _write(client, 'POST', '/api/ordering/acknowledgement', {'acknowledged': True})
    assert response.status_code == 200


def _make_persisted_run(scenario='normal'):
    run = make_run(db.session, scenario=scenario)
    db.session.commit()
    return run


def test_intro_is_versioned_and_required(seeded, client):
    _providers()
    run = _make_persisted_run()
    assert login(client).status_code == 200
    denied = _write(client, 'POST', '/api/order-drafts', {
        'store_id': run.store_id, 'run_id': run.id, 'cycle_id': run.cycle_id})
    assert denied.status_code == 422
    assert denied.json['error']['code'] == 'ACKNOWLEDGEMENT_REQUIRED'
    _acknowledge(client)
    row = db.session.execute(db.select(UserAcknowledgement)).scalar_one()
    assert row.text_version == 'ordering-intro-v1'


def test_create_and_versioned_update_preserve_suggestion(seeded, client):
    _providers()
    run = _make_persisted_run()
    assert login(client).status_code == 200
    _acknowledge(client)
    created = _write(client, 'POST', '/api/order-drafts', {
        'store_id': run.store_id, 'run_id': run.id, 'cycle_id': run.cycle_id})
    assert created.status_code == 201
    draft = created.json
    assert draft['version'] == 1 and len(draft['items']) == 10
    assert {item['final_qty'] for item in draft['items']} == {30}
    changed_id = draft['items'][0]['product_id']
    items = []
    for item in draft['items']:
        items.append({'product_id': item['product_id'],
            'final_qty': 36 if item['product_id'] == changed_id else item['final_qty'],
            'reason_code': 'promotion' if item['product_id'] == changed_id else None,
            'reason': None, 'special_need': None,
            'manual_forecast_acknowledged': False})
    updated = _write(client, 'PATCH', f"/api/order-drafts/{draft['id']}", {
        'expected_version': 1, 'items': items})
    assert updated.status_code == 200
    assert updated.json['version'] == 2
    changed = next(item for item in updated.json['items'] if item['product_id'] == changed_id)
    assert changed['final_qty'] == 36 and changed['reason_code'] == 'promotion'
    row = db.session.get(OrderDraft, draft['id'])
    item_row = db.session.execute(db.select(DraftItem).where(DraftItem.draft_id == row.id,
        DraftItem.product_id == changed_id)).scalar_one()
    assert row.status == 'DRAFT' and item_row.final_qty == 36
    stale = _write(client, 'PATCH', f"/api/order-drafts/{draft['id']}", {
        'expected_version': 1, 'items': items})
    assert stale.status_code == 409


def test_cross_store_draft_is_hidden(seeded, client):
    _providers()
    stores = db.session.execute(db.select(Store).order_by(Store.id)).scalars().all()
    run = make_run(db.session, store_id=stores[1].id)
    db.session.commit()
    assert login(client, username='manager1').status_code == 200
    _acknowledge(client)
    response = _write(client, 'POST', '/api/order-drafts', {
        'store_id': stores[1].id, 'run_id': run.id, 'cycle_id': run.cycle_id})
    assert response.status_code == 404


def test_workbench_contains_three_stages_and_accessible_labels(seeded, client):
    _providers()
    _make_persisted_run()
    assert login(client).status_code == 200
    _acknowledge(client)
    store = db.session.execute(db.select(Store).order_by(Store.id)).scalars().first()
    response = client.get(f'/store/ordering?store_id={store.id}')
    assert response.status_code == 200
    for text in ('調整數量', '核對提醒', '送出結果', '為什麼訂這個數量'):
        assert text.encode() in response.data
