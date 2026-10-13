"""Real B -> C -> D -> B loop, without order factories or providers."""
from datetime import timedelta
from time import perf_counter
from sqlalchemy import event
from app.extensions import db
from app.models import (User, Store, DeliveryCycle, Order, OrderItem, Inventory,
    ShipmentItem, BusinessClock, OrderConfirmation, OperationalTask)
from app.services.clock import business_now
from app.services.replenishment import ReplenishmentService
from app.services.orders import ordering_service
from app.services.open_orders import open_orders_service
from app.services.fulfillment import fulfillment_service
from test_submission import _write, _preview, _submit_body
from conftest import login


def real_order(app, client):
    assert app.config['MODULE_DEV'] == ''
    assert all(not test_only for _, test_only in app.extensions['service_providers'].values())
    manager = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    store = manager.stores[0]
    cycle = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id == store.id)
        .order_by(DeliveryCycle.arrival_at)).scalars().first()
    started = perf_counter()
    run = ReplenishmentService().generate(store_id=store.id, actor_id=manager.id,
        cycle_id=cycle.id, expected_version=store.calculation_version, session=db.session)
    db.session.get(BusinessClock, 1).business_anchor += timedelta(minutes=1)
    print(f'real generation: {len(run.items)} products, {perf_counter()-started:.3f}s')
    db.session.commit()
    assert login(client).status_code == 200
    assert _write(client, 'POST', '/api/ordering/acknowledgement', {'acknowledged':True}).status_code == 200
    response = _write(client, 'POST', '/api/order-drafts', {'store_id':store.id, 'run_id':run.run_id, 'cycle_id':cycle.id})
    assert response.status_code == 201, response.json
    draft = response.json
    preview = _preview(client, draft)
    assert preview['snapshot']['important_product_ids'] == []
    started = perf_counter()
    response = _write(client, 'POST', f"/api/order-drafts/{draft['id']}/submit",
        _submit_body(draft, preview), {'Idempotency-Key':'real-full-loop'})
    assert response.status_code == 201, response.json
    print(f'real submit: {perf_counter()-started:.3f}s')
    order = db.session.get(Order, response.json['order_id'])
    assert not order.fixture_only
    item = db.session.execute(db.select(OrderItem).where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)).scalars().first()
    return order, item, manager, cycle, run


def sources(order, run):
    return open_orders_service.get_open_orders(store_id=order.store_id, baseline_at=run.baseline_at,
        protection_end=run.protection_end, evaluated_at=business_now(), session=db.session).sources


def test_real_http_submit_ship_receive_and_retry(seeded, client):
    order, item, manager, cycle, run = real_order(seeded, client)
    assert item.original_qty == 30
    assert sum(s.quantity for s in sources(order, run) if s.product_id == item.product_id and s.bucket == 'U') == 30
    assert db.session.execute(db.select(db.func.count(OperationalTask.id)).where(
        OperationalTask.store_id == order.store_id, OperationalTask.task_type == 'respond_order')).scalar_one() == 10
    assert login(client, 'operator').status_code == 200
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    assert _write(client, 'POST', f'/api/fulfillment/items/{item.id}/accept', {'committed_qty':30,'eta':eta,'expected_version':order.version}).status_code == 200
    assert sum(s.quantity for s in sources(order, run) if s.product_id == item.product_id and s.bucket == 'C') == 30
    shipment = _write(client, 'POST', f'/api/fulfillment/orders/{order.id}/shipments', {
        'request_key':'real-shipment','expected_version':order.version,'lines':[dict(item_id=item.id, quantity=30, eta=eta)]})
    assert shipment.status_code == 200, shipment.json
    shipment_id = shipment.json['id']
    line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)).scalar_one()
    assert sum(s.quantity for s in sources(order, run) if s.product_id == item.product_id and s.bucket == 'C') == 30
    assert login(client).status_code == 200
    body = {'request_key':'real-receipt','expected_version':order.version,'lines':[dict(shipment_item_id=line.id,
        checked_qty=30,sellable_qty=28,damaged_qty=2,short_qty=0,note='外包裝破損，隔離處理')]}
    receipt = _write(client, 'POST', f'/api/fulfillment/shipments/{shipment_id}/receipts', body)
    assert receipt.status_code == 200, receipt.json
    stock = db.session.execute(db.select(Inventory).where(Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    assert (stock.book_physical_qty, stock.book_unsellable_qty) == (50,2)
    assert not [s for s in sources(order, run) if s.product_id == item.product_id]
    assert _write(client, 'POST', f'/api/fulfillment/shipments/{shipment_id}/receipts', body).json['id'] == receipt.json['id']
    assert stock.book_physical_qty == 50
    assert login(client,'manager2').status_code == 200
    assert client.get(f'/api/fulfillment/orders/{order.id}').status_code == 404
    assert _write(client, 'POST', f'/api/fulfillment/shipments/{shipment_id}/receipts', body).status_code == 404
    assert item.original_qty == 30
    confirmation = db.session.execute(db.select(OrderConfirmation).where(OrderConfirmation.order_id == order.id)).scalar_one()
    assert confirmation.snapshot['items'][0]['final_qty'] == 30


def test_real_receipt_inventory_failure_rolls_back_everything(seeded, client, monkeypatch):
    order, item, manager, cycle, run = real_order(seeded, client)
    operator = db.session.execute(db.select(User).where(User.username == 'operator')).scalar_one()
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30, eta=eta, session=db.session)
    shipment = fulfillment_service.ship(order_id=order.id, actor_id=operator.id, request_key='rollback-ship',
        lines=[dict(item_id=item.id,quantity=30,eta=eta)], session=db.session)
    db.session.commit()
    line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id==shipment.id)).scalar_one()
    body = {'request_key':'rollback-receipt','expected_version':order.version,'lines':[dict(shipment_item_id=line.id,checked_qty=30,
        sellable_qty=30,damaged_qty=0,short_qty=0)]}
    from app.services.inventory import InventoryService
    original = InventoryService.apply_movement
    def fail_after_real_write(self, *args, **kwargs):
        original(self,*args,**kwargs)
        raise RuntimeError('injected failure after real B write')
    monkeypatch.setattr(InventoryService, 'apply_movement', fail_after_real_write)
    failed = _write(client,'POST',f'/api/fulfillment/shipments/{shipment.id}/receipts',body)
    assert failed.status_code == 500
    db.session.expire_all()
    assert line.checked_qty == 0
    stock = db.session.execute(db.select(Inventory).where(Inventory.store_id==order.store_id,
        Inventory.product_id==item.product_id)).scalar_one()
    assert stock.book_physical_qty == 20
    monkeypatch.setattr(InventoryService, 'apply_movement', original)
    assert _write(client,'POST',f'/api/fulfillment/shipments/{shipment.id}/receipts',body).status_code == 200
    assert stock.book_physical_qty == 50


def test_open_order_query_count_is_bounded(seeded, client):
    order, item, manager, cycle, run = real_order(seeded, client)
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'): statements.append(statement)
    engine=db.engine
    event.listen(engine,'before_cursor_execute',capture)
    try: rows=sources(order,run)
    finally: event.remove(engine,'before_cursor_execute',capture)
    assert len(rows)==10
    assert len(statements)<=6, len(statements)


def test_fulfillment_requires_current_version_and_preserves_first_result(seeded,client):
    order,item,manager,cycle,run=real_order(seeded,client)
    assert login(client,'operator').status_code==200
    eta=cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    path=f'/api/fulfillment/items/{item.id}/accept'
    body={'committed_qty':30,'eta':eta}
    assert _write(client,'POST',path,body).status_code==422
    version=order.version
    assert _write(client,'POST',path,{**body,'expected_version':version}).status_code==200
    assert _write(client,'POST',f'/api/fulfillment/items/{item.id}/changes',dict(committed_qty=20,eta=eta,
        reason='另一分頁已變更',expected_version=version)).status_code==409
    assert item.committed_qty==30
