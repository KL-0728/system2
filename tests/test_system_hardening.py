"""A regression evidence on MySQL using real B/C/D services."""
from datetime import timedelta
import pytest
from app.extensions import db
from app.models import Product, User, OperationalTask, ShipmentItem
from app.services.management import save, serialize
from app.services.errors import DomainError
from app.services.fulfillment import fulfillment_service as service
from app.services.replenishment import ReplenishmentService
from test_full_integration import real_order
from conftest import login
from test_submission import _write


def setup_order(seeded, client):
    order, item, manager, cycle, run = real_order(seeded, client)
    operator = db.session.execute(db.select(User).where(User.username == 'operator')).scalar_one()
    admin = db.session.execute(db.select(User).where(User.username == 'admin')).scalar_one()
    return order, item, manager, cycle, run, operator, admin


def test_disabled_product_keeps_sources_without_blocking_other_products(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    product = db.session.get(Product, item.product_id)
    save(admin, 'products', {**serialize('products', product), 'active':False}, product.id)
    result = ReplenishmentService().generate(store_id=order.store_id, actor_id=manager.id,
        cycle_id=cycle.id, expected_version=manager.stores[0].calculation_version, session=db.session)
    assert item.product_id not in {i.product_id for i in result.items}
    from test_full_integration import sources
    assert any(s.product_id == item.product_id for s in sources(order, run))


def test_store_with_open_order_cannot_be_disabled(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    store = manager.stores[0]
    with pytest.raises(DomainError) as error:
        save(admin, 'stores', {**serialize('stores', store), 'active':False}, store.id)
    assert error.value.code == 'STORE_HAS_UNFINISHED_WORK'
    assert error.value.details['blockers']
    assert store.active


def test_used_product_unit_is_immutable(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    product = db.session.get(Product, item.product_id)
    with pytest.raises(DomainError) as error:
        save(admin, 'products', {**serialize('products', product), 'base_unit':'公斤'}, product.id)
    assert error.value.code == 'BASE_UNIT_LOCKED'
    assert product.base_unit == '件'


def test_late_shipment_requires_reason_preserves_commitment(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo)
    service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30, eta=eta.isoformat(), session=db.session)
    with pytest.raises(DomainError) as error:
        service.ship(order_id=order.id, actor_id=operator.id, request_key='late',
            lines=[dict(item_id=item.id, quantity=30, eta=(eta+timedelta(hours=2)).isoformat())], session=db.session)
    assert error.value.code == 'DELAY_REASON_REQUIRED'
    shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='late',
        lines=[dict(item_id=item.id, quantity=30, eta=(eta+timedelta(hours=2)).isoformat(), delay_reason='車輛故障延遲')], session=db.session)
    assert item.eta == cycle.arrival_at
    line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id == shipment.id)).scalar_one()
    assert line.eta_disputed
    assert db.session.execute(db.select(OperationalTask).where(OperationalTask.source_id == str(line.id),
        OperationalTask.task_type == 'investigate_shipment', OperationalTask.completed_at.is_(None))).scalar_one()


def test_second_unknown_has_new_task_and_new_receipt_deadline(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo)
    service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30, eta=eta.isoformat(), session=db.session)
    shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='unknown',
        lines=[dict(item_id=item.id, quantity=30, eta=eta.isoformat())], session=db.session)
    line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id == shipment.id)).scalar_one()
    service.mark_unknown(shipment_item_id=line.id, actor_id=manager.id, reason='尚未抵達', session=db.session)
    service.resolve_unknown(shipment_item_id=line.id, actor_id=operator.id, eta=(eta+timedelta(hours=2)).isoformat(), reason='確認仍在途', session=db.session)
    service.mark_unknown(shipment_item_id=line.id, actor_id=manager.id, reason='再次未抵達', session=db.session)
    db.session.flush()
    tasks = db.session.execute(db.select(OperationalTask).where(OperationalTask.source_id == str(line.id),
        OperationalTask.task_type == 'investigate_shipment').order_by(OperationalTask.id)).scalars().all()
    assert len(tasks) == 2
    assert tasks[0].completed_at and tasks[1].completed_at is None
    receipt = db.session.execute(db.select(OperationalTask).where(OperationalTask.source_id == str(line.id),
        OperationalTask.task_type == 'receive_shipment', OperationalTask.completed_at.is_(None))).scalar_one()
    assert receipt.due_at > eta.replace(tzinfo=None) + timedelta(hours=2)


def test_cross_day_cycles_auto_prepare_and_window_remains_strict(seeded, client):
    from app.models import BusinessClock, DeliveryCycle, Store
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor = clock.business_anchor.replace(minute=0) + timedelta(days=1)
    db.session.commit()
    assert login(client).status_code == 200
    store = db.session.execute(db.select(Store).where(Store.code == 'DEMO1')).scalar_one()
    first = client.get(f'/api/replenishment/context?store_id={store.id}')
    assert first.status_code == 200 and first.json['can_generate']
    assert len(first.json['cycles']) >= 3
    version = first.json['store_version']
    second = client.get(f'/api/replenishment/context?store_id={store.id}')
    assert second.json['cycles'] == first.json['cycles'] and second.json['store_version'] == version
    clock.business_anchor += timedelta(hours=1)
    db.session.commit()
    closed = client.get(f'/api/replenishment/context?store_id={store.id}').json
    assert not closed['can_generate'] and closed['window_status'] == 'closed'
    assert closed['next_open_at'] > closed['cutoff_at']
    assert _write(client, 'POST', '/api/replenishment/runs', dict(store_id=store.id,
        cycle_id=first.json['cycles'][0]['id'], expected_version=closed['store_version'])).status_code == 409
    clock.business_anchor += timedelta(hours=22, minutes=59)
    db.session.commit()
    before = client.get(f'/api/replenishment/context?store_id={store.id}').json
    assert before['window_status'] == 'before_open' and not before['can_generate']


def test_idle_expiry_requires_login_and_original_permissions(seeded, client):
    assert login(client).status_code == 200
    from time import time
    with client.session_transaction() as session:
        session['last_activity'] = time() - 1801
    assert client.get('/api/auth/me').status_code == 401
    assert login(client, 'manager2').status_code == 200
    manager1 = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    assert client.get(f'/api/orders?store_id={manager1.stores[0].id}').status_code == 404


def test_order_filters_validate_and_keep_store_scope(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    query = f'?store_id={order.store_id}&number={order.number}&status=SUBMITTED&from_date=2026-10-08&to_date=2026-10-08'
    assert client.get('/api/orders'+query).json['total'] == 1
    assert client.get('/api/orders'+query.replace('2026-10-08','2026-10-09')).json['total'] == 0
    assert client.get('/api/orders'+query+'&status=SHIPPED').status_code == 400
    assert client.get(f'/api/orders?store_id={order.store_id}&status=UNKNOWN').status_code == 400
    assert client.get(f'/api/orders?store_id={order.store_id}&from_date=bad').status_code == 400
    assert client.get(f'/api/orders?store_id={order.store_id}&from_date=0001-01-01').status_code == 400
    assert client.get(f'/api/orders?store_id={order.store_id}&to_date=9999-12-31').status_code == 400
    assert login(client, 'manager2').status_code == 200
    assert client.get('/api/orders'+query).status_code == 404


def test_state_transition_key_recovers_original_result_and_rejects_change(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    assert login(client, 'operator').status_code == 200
    path = f'/api/fulfillment/items/{item.id}/accept'
    body = dict(expected_version=order.version, request_key='accept-recovery', committed_qty=30,
        eta=cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat())
    first = _write(client, 'POST', path, body)
    assert first.status_code == 200, first.json
    version = order.version
    retry = _write(client, 'POST', path, body)
    assert retry.json == first.json and order.version == version
    conflict = _write(client, 'POST', path, {**body,'committed_qty':29})
    assert conflict.status_code == 409 and conflict.json['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_rebuild_preserves_manual_data_resets_confirmation_and_archives(seeded, client):
    from app.models import OrderDraft, OrderConfirmation
    from app.services.orders import ordering_service
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    def new_run():
        return ReplenishmentService().generate(store_id=order.store_id, actor_id=manager.id,
            cycle_id=cycle.id, expected_version=manager.stores[0].calculation_version, session=db.session)
    current = new_run()
    draft = ordering_service.create_draft(manager, store_id=order.store_id, run_id=current.run_id, cycle_id=cycle.id)
    changed = ordering_service.update_draft(manager, draft['id'], {'expected_version':draft['version'],
        'items':[dict(product_id=item.product_id, final_qty=6, reason_code='promotion', reason='本地活動調整備貨',
            special_need={'need_date':'2026-10-09','need_qty':6,'arrangement':'活動现场交付'}, manual_forecast_acknowledged=True)]})
    new_run()
    rebuilt = ordering_service.rebuild_draft(manager, changed['id'], changed['version'])
    line = next(i for i in rebuilt['items'] if i['product_id'] == item.product_id)
    assert line['final_qty'] == 6 and line['reason'] == '本地活動調整備貨'
    assert line['special_need']['need_qty'] == 6 and not line['manual_forecast_acknowledged']
    assert db.session.get(OrderDraft, changed['id']).status == 'ARCHIVED'
    assert not db.session.execute(db.select(OrderConfirmation.id).where(OrderConfirmation.draft_id == rebuilt['id'])).first()
    with pytest.raises(DomainError):
        ordering_service.rebuild_draft(manager, changed['id'], changed['version'])


def test_model_comparison_real_next_interval_sales_and_store_isolation(seeded, client):
    from app.models import BusinessClock, Inventory
    from app.services.sales import SalesService
    from test_sales import csv_text
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    initial = client.get(f'/store/model-performance?store_id={order.store_id}')
    assert initial.status_code == 200 and '合成'.encode() in initial.data
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor += timedelta(days=1)
    rows = db.session.execute(db.select(Inventory).where(Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalars().all()
    case = {'store':manager.stores[0], 'b':run.baseline_at+timedelta(days=1), 'rows':rows}
    payload = dict(store_id=order.store_id, import_mode='historical',
        csv_text=csv_text(case, source='model-evaluation', sold=18), replaces_batch_id=None, reason='合成模型比較')
    sales = SalesService()
    validated = sales.validate(payload=payload, actor_id=manager.id, session=db.session)
    sales.commit(payload=payload, actor_id=manager.id, validation_token=validated['validation_token'], session=db.session)
    db.session.commit()
    result = client.get(f'/store/model-performance?store_id={order.store_id}')
    assert result.status_code == 200
    assert '實際銷量 18'.encode() in result.data
    assert '本頁有效樣本 1'.encode() in result.data
    assert login(client,'manager2').status_code == 200
    assert client.get(f'/store/model-performance?store_id={order.store_id}').status_code == 404


def test_batch_receipt_second_inventory_failure_rolls_back_and_replays(seeded, client, monkeypatch):
    from app.models import OrderItem, Inventory, Receipt
    from app.services.inventory import InventoryService
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    items = db.session.execute(db.select(OrderItem).where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id).limit(2)).scalars().all()
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    for item in items:
        service.accept(item_id=item.id, actor_id=operator.id, committed_qty=item.original_qty, eta=eta, session=db.session)
    shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='batch-original',
        lines=[dict(item_id=i.id,quantity=i.original_qty,eta=eta) for i in items],session=db.session)
    db.session.commit()
    lines = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id == shipment.id)).scalars().all()
    body = dict(expected_version=order.version,request_key='batch-atomic',lines=[dict(shipment_item_id=l.id,
        checked_qty=30,sellable_qty=30,damaged_qty=0,short_qty=0) for l in lines])
    original = InventoryService.apply_movement
    calls = 0
    def fail_second(self, *args, **kwargs):
        nonlocal calls
        result = original(self,*args,**kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError('controlled failure after second real inventory write')
        return result
    monkeypatch.setattr(InventoryService,'apply_movement',fail_second)
    path = f'/api/fulfillment/shipments/{shipment.id}/receipts'
    assert _write(client,'POST',path,body).status_code == 500
    db.session.expire_all()
    stocks = db.session.execute(db.select(Inventory).where(Inventory.store_id==order.store_id,
        Inventory.product_id.in_([i.product_id for i in items]))).scalars().all()
    assert all(s.book_physical_qty==20 for s in stocks)
    assert not db.session.execute(db.select(Receipt.id).where(Receipt.shipment_id==shipment.id)).first()
    assert all(l.checked_qty==0 for l in lines)
    monkeypatch.setattr(InventoryService,'apply_movement',original)
    saved = _write(client,'POST',path,body)
    assert saved.status_code == 200,saved.json
    assert all(s.book_physical_qty==50 for s in stocks)
    assert _write(client,'POST',path,body).json['id'] == saved.json['id']
    assert all(s.book_physical_qty==50 for s in stocks)
