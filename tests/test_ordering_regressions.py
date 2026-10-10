"""A's integration fixes for exclusions and complete special-demand inputs."""
from dataclasses import replace
from datetime import timedelta

import pytest

from app.contracts import WarningDTO
from app.extensions import db
from app.models import Order, OrderItem, Store, BusinessClock, DeliveryCycle
from app.providers import register_provider
from app.testing.providers import ControlledIntegrity, ControlledRuns
from test_submission import _prepare, _save, _preview, _submit_body, _write


@pytest.mark.parametrize('offset', [-1, 60])
def test_round_boundary_blocks_new_preview(seeded, client, offset):
    _, draft = _prepare(seeded, client)
    cycle = db.session.get(DeliveryCycle, draft['cycle_id'])
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = cycle.baseline_at + timedelta(minutes=offset)
    db.session.commit()
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/preview",
                      {'expected_version': draft['version']})
    assert response.status_code == 409


@pytest.mark.parametrize('revocation', ['inactive', 'membership'])
def test_draft_read_rechecks_store_permission(seeded, client, revocation):
    _, draft = _prepare(seeded, client)
    store = db.session.get(Store, draft['store_id'])
    if revocation == 'inactive':
        store.active = False
    else:
        from app.models import User
        actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
        actor.stores.remove(store)
    db.session.commit()
    assert client.get(f"/api/order-drafts/{draft['id']}").status_code == 404


@pytest.mark.parametrize('body', [[], ['unexpected'], None, 'text', 12])
def test_non_object_login_json_rejected(seeded, client, body):
    response = _write(client, 'POST', '/api/auth/login', body)
    assert response.status_code == 400


def test_workbench_ignores_newer_fulfillment_factory(seeded, client):
    run, draft = _prepare(seeded, client)
    from app.testing.factories import make_order
    make_order(db.session, store_id=run.store_id)
    db.session.commit()
    page = client.get(f'/store/ordering?store_id={run.store_id}')
    assert page.status_code == 200
    import json
    from html import unescape
    bootstrap = json.loads(unescape(page.get_data(as_text=True).split('<script id="ordering-bootstrap" type="application/json">')[1].split('</script>')[0]))
    assert bootstrap['run']['run_id'] == run.id
    assert all(item['run_item_id'] for item in bootstrap['run']['items'])
    assert client.get(f"/store/ordering?store_id={run.store_id}&draft_id={draft['id']}").status_code == 200


def test_successful_retry_after_cutoff_and_order_pagination(seeded, client):
    run, draft = _prepare(seeded, client)
    first_body = None
    for number in range(21):
        if number:
            response = _write(client, 'POST', '/api/order-drafts', {
                'store_id': run.store_id, 'run_id': run.id, 'cycle_id': run.cycle_id})
            assert response.status_code == 201
            draft = response.json
        preview = _preview(client, draft)
        body = _submit_body(draft, preview)
        response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit", body,
                          {'Idempotency-Key': f'pagination-{number}'})
        assert response.status_code == 201
        if number == 0:
            first_body = (draft['id'], body, response.json['order_id'])
    first = client.get(f'/api/orders?store_id={run.store_id}').json
    second = client.get(f'/api/orders?store_id={run.store_id}&page=2').json
    assert len(first['orders']) == 20 and first['has_next'] and first['total'] == 21
    assert len(second['orders']) == 1 and not second['has_next']
    assert {row['id'] for row in first['orders']}.isdisjoint({row['id'] for row in second['orders']})
    cycle = db.session.get(DeliveryCycle, run.cycle_id)
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = cycle.cutoff_at + timedelta(minutes=10)
    db.session.commit()
    replay = _write(client, 'POST', f'/api/order-drafts/{first_body[0]}/submit', first_body[1],
                    {'Idempotency-Key': 'pagination-0'})
    assert replay.status_code == 200 and replay.json['order_id'] == first_body[2]


def _acks(preview, handling='special_arrangement'):
    return [{'product_id': product_id, 'warning_version': '1',
             'acknowledged': True, 'handling': handling,
             'reason': '已核對特殊需求與收貨安排'}
            for product_id in preview['snapshot']['important_product_ids']]


def test_short_important_reason_names_product_and_remedy(seeded, client):
    _, draft = _prepare(seeded, client)
    draft = _save(client, draft, lambda value, item: {
        **value, 'final_qty': 120, 'reason_code': 'local_demand', 'reason': '下雨天'}
        if item['name'] == '雨衣' else value)
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/preview",
                      {'expected_version': draft['version']})
    assert response.status_code == 422
    error = response.json['error']
    assert '雨衣' in error['message'] and '10' in error['message']
    assert error['details']['items'][0]['name'] == '雨衣'
    assert '10' in error['details']['items'][0]['messages'][0]


@pytest.mark.parametrize('scenario', ['direct', 'model'])
@pytest.mark.parametrize('bad_fields', [
    None, {}, {'need_date': '2026-02-30', 'need_qty': 12, 'arrangement': '到貨交付'},
    {'need_date': '2026-10-10', 'need_qty': True, 'arrangement': '到貨交付'},
    {'need_date': '2026-10-10', 'need_qty': 0, 'arrangement': '到貨交付'},
    {'need_date': '2026-10-10', 'need_qty': 1.5, 'arrangement': '到貨交付'},
    {'need_date': '2026-10-10', 'need_qty': 12, 'arrangement': '   '},
])
def test_incomplete_special_need_is_rejected(seeded, client, scenario, bad_fields):
    _, draft = _prepare(seeded, client, scenario)
    draft = _save(client, draft, lambda value, item: {
        **value, 'final_qty': item['pack_size'], 'reason_code': 'local_demand',
        'reason': '社區活動需要商品，請按本次數量供貨',
        'special_need': bad_fields if scenario == 'direct' or bad_fields is not None else {},
    })
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/preview",
                      {'expected_version': draft['version']})
    assert response.status_code == 422
    assert response.json['error']['code'] == 'SPECIAL_NEED_REQUIRED'
    assert db.session.execute(db.select(db.func.count(Order.id))).scalar_one() == 0


@pytest.mark.parametrize('scenario', ['unavailable', 'direct', 'inventory_gap'])
def test_excluded_item_does_not_block_valid_items(seeded, client, scenario):
    _, draft = _prepare(seeded, client)
    excluded_id = draft['items'][0]['product_id']

    class OneUnavailable(ControlledRuns):
        def evaluate(self, **kwargs):
            run = super().evaluate(**kwargs)
            return replace(run, items=tuple(
                replace(item, mode=scenario, mu=None, suggested_qty=None,
                        target_stock=None, raw_qty=None,
                        timeline_committed=(), timeline_with_pending=(),
                        warnings=(WarningDTO('FORECAST_INSUFFICIENT' if scenario == 'unavailable'
                                             else 'DIRECT_ORDER', '資料不足', {}),))
                if item.product_id == excluded_id else item for item in run.items))

    class OneGap(ControlledIntegrity):
        def get_integrity(self, **kwargs):
            if kwargs['product_id'] == excluded_id:
                return ControlledIntegrity('gap').get_integrity(**kwargs)
            return super().get_integrity(**kwargs)

    if scenario == 'inventory_gap':
        register_provider('integrity', OneGap(), test_only=True)
    else:
        register_provider('runs', OneUnavailable(), test_only=True)
    draft = _save(client, draft, lambda value, item: {
        **value, 'final_qty': 0, 'reason_code': 'skip'}
        if value['product_id'] == excluded_id else value)
    preview = _preview(client, draft)
    excluded = next(item for item in preview['snapshot']['items'] if item['product_id'] == excluded_id)
    assert excluded['final_qty'] == 0 and excluded['warnings']
    assert excluded_id not in preview['snapshot']['important_product_ids']
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
                      _submit_body(draft, preview), {'Idempotency-Key': f'excluded-{scenario}'})
    assert response.status_code == 201
    ordered = db.session.execute(db.select(OrderItem).where(
        OrderItem.order_id == response.json['order_id'])).scalars().all()
    assert len(ordered) == 9
    assert excluded_id not in {item.product_id for item in ordered}


def test_exclude_handling_requires_edit_and_new_preview(seeded, client):
    _, draft = _prepare(seeded, client)
    excluded_id = draft['items'][0]['product_id']
    draft = _save(client, draft, lambda value, item: {
        **value, 'final_qty': 120, 'reason_code': 'local_demand',
        'reason': '社區活動需要商品，已安排現場交付'}
        if value['product_id'] == excluded_id else value)
    preview = _preview(client, draft)
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
                      _submit_body(draft, preview, _acks(preview, 'exclude')),
                      {'Idempotency-Key': 'exclude-positive'})
    assert response.status_code == 422
    assert response.json['error']['code'] == 'EXCLUSION_REQUIRES_EDIT'
    assert db.session.execute(db.select(db.func.count(Order.id))).scalar_one() == 0
    draft = _save(client, draft, lambda value, item: {
        **value, 'final_qty': 0, 'reason_code': 'skip'}
        if value['product_id'] == excluded_id else value)
    stale = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
                   _submit_body(draft, preview), {'Idempotency-Key': 'old-preview'})
    assert stale.status_code == 409
    fresh = _preview(client, draft)
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
                      _submit_body(draft, fresh), {'Idempotency-Key': 'exclude-complete'})
    assert response.status_code == 201


def test_positive_inventory_gap_still_blocks(seeded, client):
    _, draft = _prepare(seeded, client)
    register_provider('integrity', ControlledIntegrity('gap'), test_only=True)
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/preview",
                      {'expected_version': draft['version']})
    assert response.status_code == 422
    assert response.json['error']['code'] == 'PREVIEW_BLOCKED'
