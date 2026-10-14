"""Six review regressions, using the isolated MySQL transaction and real services."""
from datetime import timedelta
import pytest
from conftest import login
from test_sales import sales_case, csv_text, payload, validated, commit
from test_system_hardening import setup_order
from test_submission import _write
from app.extensions import db
from app.models import (Product, StoreProduct, SalesDaily, SalesImportBatch, InventoryMovement,
    OperationalTask, PolicyVersion, BusinessClock, ShipmentItem, OrderDraft, Store, User, Shipment, DeliveryCycle)
from app.services.clock import business_now, utc_naive, aware, TAIPEI
from app.services.fulfillment import fulfillment_service as service
from app.services.orders import ordering_service
from app.services.replenishment import ReplenishmentService
from app.services.errors import DomainError
from app.services.tasks import serialize_tasks


@pytest.mark.parametrize('product_active,link_active', [(False, True), (True, False), (False, False)])
def test_disabled_catalog_entries_remain_excluded_from_new_ordering(seeded, client, product_active, link_active):
    manager = db.session.execute(db.select(User).where(User.username=='manager1')).scalar_one()
    store=manager.stores[0]
    link=db.session.execute(db.select(StoreProduct).where(StoreProduct.store_id==store.id).order_by(StoreProduct.product_id)).scalars().first()
    db.session.get(Product,link.product_id).active=product_active
    link.active=link_active
    cycle=db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==store.id).order_by(DeliveryCycle.arrival_at)).scalars().first()
    run=ReplenishmentService().generate(store_id=store.id,actor_id=manager.id,cycle_id=cycle.id,
        expected_version=store.calculation_version,session=db.session)
    assert link.product_id not in {i.product_id for i in run.items}
    assert run.items  # Other active products still have real suggestions.


@pytest.mark.parametrize('product_active,link_active', [(False, True), (True, False), (False, False)])
@pytest.mark.parametrize('mode', ['historical', 'daily_posting'])
def test_inactive_sales_mixed_batch_and_correction(sales_case, product_active, link_active, mode):
    c = sales_case
    first_product = db.session.get(Product, c['rows'][0].product_id)
    link = db.session.execute(db.select(StoreProduct).where(StoreProduct.store_id == c['store'].id,
        StoreProduct.product_id == first_product.id)).scalar_one()
    first_product.active, link.active = product_active, link_active
    db.session.commit()
    original_stocks = [i.book_physical_qty for i in c['rows'][:2]]
    first = commit(c, validated(c, payload(c, import_mode=mode, csv_text=csv_text(c, count=2))))
    assert first.status_code == 201, first.json
    corrected = payload(c, import_mode=mode, csv_text=csv_text(c, 'inactive-correction', sold=4, count=2),
        replaces_batch_id=first.json['batch_id'], reason='修正停用前實際銷量')
    result = commit(c, validated(c, corrected))
    assert result.status_code == 201, result.json
    replay = commit(c, {**corrected, 'validation_token': 'already-succeeded'})
    assert replay.status_code == 200 and replay.json['batch_id'] == result.json['batch_id']
    rows = db.session.execute(db.select(SalesDaily).where(SalesDaily.batch_id == result.json['batch_id'])).scalars().all()
    assert len(rows) == 2 and all(r.sold_qty == 4 for r in rows)
    assert [i.book_physical_qty for i in c['rows'][:2]] == [q - (4 if mode == 'daily_posting' else 0) for q in original_stocks]
    assert not first_product.active or not link.active


@pytest.mark.parametrize('bad', ['unknown', 'unlinked', 'wrong_store'])
def test_bad_sales_mixed_with_inactive_is_atomic(sales_case, bad):
    c = sales_case
    product = db.session.get(Product, c['rows'][0].product_id)
    product.active = False
    text = csv_text(c, count=2)
    if bad == 'unknown':
        other = db.session.get(Product, c['rows'][1].product_id)
        text = text.replace(other.sku, 'DOES-NOT-EXIST')
    elif bad == 'unlinked':
        other = db.session.get(Product, c['rows'][1].product_id)
        db.session.add(Product(sku='UNLINKED', name='未關聯商品', base_unit='件', pack_size=1, active=True))
        text = text.replace(other.sku, 'UNLINKED')
    else:
        lines = text.splitlines()
        lines[2] = lines[2].replace(c['store'].code, 'OTHER-STORE')
        text = '\n'.join(lines) + '\n'
    db.session.commit()
    before = db.session.scalar(db.select(db.func.count(SalesImportBatch.id)))
    stocks = [i.book_physical_qty for i in c['rows'][:2]]
    data = payload(c, csv_text=text, import_mode='historical')
    result = c['client'].post('/api/sales/import/validate', json=data, headers=c['headers'])
    assert result.status_code == 200 and not result.json['valid']
    assert ('STORE_MISMATCH' if bad == 'wrong_store' else 'UNKNOWN_PRODUCT') in {e['code'] for e in result.json['errors']}
    rejected = commit(c, {**data, 'validation_token': 'invalid'})
    assert rejected.status_code == (422 if bad == 'wrong_store' else 409)
    assert rejected.json['error']['code'] == ('CSV_INVALID' if bad == 'wrong_store' else 'VALIDATION_EXPIRED')
    assert db.session.scalar(db.select(db.func.count(SalesImportBatch.id))) == before
    assert [i.book_physical_qty for i in c['rows'][:2]] == stocks


def new_draft(order, manager, cycle):
    run = ReplenishmentService().generate(store_id=order.store_id, actor_id=manager.id,
        cycle_id=cycle.id, expected_version=manager.stores[0].calculation_version, session=db.session)
    return ordering_service.create_draft(manager, store_id=order.store_id, run_id=run.run_id, cycle_id=cycle.id)


@pytest.mark.parametrize('action', ['archive', 'rebuild'])
def test_stale_draft_action_does_not_change_saved_data(seeded, client, action):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    draft = new_draft(order, manager, cycle)
    updated = ordering_service.update_draft(manager, draft['id'], {'expected_version':draft['version'],
        'items':[dict(product_id=item.product_id, final_qty=6, reason_code='promotion', reason='另一視窗已更新')]})
    db.session.commit()
    result = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/{action}", {'expected_version':draft['version']})
    assert result.status_code == 409
    saved = ordering_service.get_draft(manager, draft['id'])
    assert saved['status'] == 'DRAFT' and saved['version'] == updated['version']
    assert next(i for i in saved['items'] if i['product_id']==item.product_id)['reason'] == '另一視窗已更新'


def test_home_selects_authorized_second_store_and_archived_draft(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    second = db.session.execute(db.select(Store).where(Store.code == 'DEMO2')).scalar_one()
    manager.stores.append(second)
    second_cycle = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==second.id)).scalars().first()
    second_run = ReplenishmentService().generate(store_id=second.id, actor_id=manager.id, cycle_id=second_cycle.id,
        expected_version=second.calculation_version, session=db.session)
    draft = ordering_service.create_draft(manager, store_id=second.id, run_id=second_run.run_id, cycle_id=second_cycle.id)
    ordering_service.archive_draft(manager, draft['id'], draft['version'])
    db.session.commit()
    assert login(client).status_code == 200
    page = client.get(f'/?store_id={second.id}')
    assert page.status_code == 200
    assert f'草稿 #{draft["id"]}'.encode() in page.data
    assert f'store_id={second.id}'.encode() in page.data
    assert 'DEMO2 · 門市工作區'.encode() in page.data
    assert client.get('/?store_id=bad').status_code == 400
    assert client.get('/?store_id=9999999999').status_code == 404
    assert login(client, 'manager2').status_code == 200
    assert client.get(f'/?store_id={order.store_id}').status_code == 404
    assert login(client, 'admin').status_code == 200
    assert 'DEMO2 · 門市工作區'.encode() in client.get(f'/?store_id={second.id}').data
    second.active = False
    db.session.commit()
    assert client.get(f'/?store_id={second.id}').status_code == 404


@pytest.mark.parametrize('delay_seconds', [0, 1])
def test_investigation_policy_threshold_replay_rounds_and_time_boundary(seeded, client, delay_seconds):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    policy = db.session.execute(db.select(PolicyVersion).where(PolicyVersion.store_id==order.store_id,
        PolicyVersion.product_id==item.product_id).order_by(PolicyVersion.version.desc())).scalars().first()
    from app.services.management import save, serialize
    link = db.session.execute(db.select(StoreProduct).where(StoreProduct.store_id==order.store_id,
        StoreProduct.product_id==item.product_id)).scalar_one()
    save(admin, 'policies', {**serialize('policies', link), 'contact_minutes':17}, link.id)
    eta = aware(cycle.arrival_at)
    service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30, eta=eta.isoformat(), session=db.session)
    # Cross Taipei midnight while storing UTC, with a fractional minute deadline.
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = utc_naive(business_now().astimezone(TAIPEI).replace(hour=23, minute=59, second=59, microsecond=0))
    now = business_now()
    lines = [dict(item_id=item.id, quantity=30, eta=(eta+timedelta(seconds=delay_seconds)).astimezone(TAIPEI).isoformat(), delay_reason='配送延遲')]
    shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='policy-delay', lines=lines, session=db.session)
    db.session.flush()
    line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id==shipment.id)).scalar_one()
    def investigations():
        return db.session.execute(db.select(OperationalTask).where(OperationalTask.source_id==str(line.id),
            OperationalTask.task_type=='investigate_shipment').order_by(OperationalTask.round)).scalars().all()
    tasks = investigations()
    assert len(tasks) == delay_seconds
    if delay_seconds:
        assert tasks[0].due_at == utc_naive(now+timedelta(minutes=17))
        assert tasks[0].policy_version_id != policy.id
    assert service.ship(order_id=order.id, actor_id=operator.id, request_key='policy-delay', lines=lines, session=db.session).id == shipment.id
    assert len(investigations()) == delay_seconds
    if not delay_seconds:
        service.mark_unknown(shipment_item_id=line.id, actor_id=manager.id, reason='尚未到货', session=db.session)
    db.session.flush()
    first = investigations()[0]
    assert first.due_at == utc_naive(now+timedelta(minutes=17))
    clock.business_anchor = first.due_at
    assert not serialize_tasks(db.session, [first], 'operator')[0]['overdue']
    clock.business_anchor += timedelta(seconds=1)
    assert serialize_tasks(db.session, [first], 'operator')[0]['overdue']
    service.resolve_unknown(shipment_item_id=line.id, actor_id=operator.id, eta=(eta+timedelta(days=1)).isoformat(),
        reason='查明在途，重新排程', session=db.session)
    assert first.completed_at and first.due_at == utc_naive(now+timedelta(minutes=17))
    assert serialize_tasks(db.session, [first], 'operator')[0]['was_overdue']
    save(admin, 'policies', {**serialize('policies', link), 'contact_minutes':23}, link.id)
    second_now = business_now()
    service.mark_unknown(shipment_item_id=line.id, actor_id=manager.id, reason='再度待查', session=db.session)
    db.session.flush()
    assert len(investigations()) == 2
    second = investigations()[1]
    assert second.round == 2 and second.due_at == utc_naive(second_now+timedelta(minutes=23))
    assert second.policy_version_id != first.policy_version_id
    with pytest.raises(DomainError):
        service.mark_unknown(shipment_item_id=line.id, actor_id=manager.id, reason='重複事件', session=db.session)
    assert len(investigations()) == 2


def test_fulfillment_actor_binding_rejects_other_account_before_write(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    assert login(client, 'admin').status_code == 200
    before = item.status
    result = _write(client, 'POST', f'/api/fulfillment/items/{item.id}/accept', dict(expected_actor_id=operator.id,
        expected_version=order.version, request_key='old-operator', committed_qty=30, eta=aware(cycle.arrival_at).isoformat()))
    assert result.status_code == 401 and result.json['error']['code']=='ACTOR_CHANGED'
    assert item.status == before
