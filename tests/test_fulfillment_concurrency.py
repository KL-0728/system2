"""Two independent connections enter real D receipt after a stale MySQL snapshot."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
import pytest
from app.extensions import db
from app.models import User, ShipmentItem, Inventory, Receipt
from app.services.fulfillment import fulfillment_service
from test_ordering_concurrency import committed_app
from test_full_integration import real_order
from conftest import login
from test_submission import _write


@pytest.mark.parametrize('same_key',[True,False])
def test_two_real_receipts_never_double_book(committed_app,monkeypatch,same_key):
    client=committed_app.test_client()
    order,item,manager,cycle,run=real_order(committed_app,client)
    operator=db.session.execute(db.select(User).where(User.username=='operator')).scalar_one()
    eta=cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    fulfillment_service.accept(item_id=item.id,actor_id=operator.id,committed_qty=30,eta=eta,session=db.session)
    shipment=fulfillment_service.ship(order_id=order.id,actor_id=operator.id,request_key='race-ship',
        lines=[dict(item_id=item.id,quantity=30,eta=eta)],session=db.session)
    db.session.commit()
    line=db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id==shipment.id)).scalar_one()
    shipment_id,line_id,store_id,product_id=shipment.id,line.id,order.store_id,item.product_id
    version=order.version
    db.session.remove()
    clients=[committed_app.test_client(),committed_app.test_client()]
    for c in clients:
        with committed_app.app_context(): assert login(c).status_code==200
    import app.services.fulfillment_requests as module
    original=module.lock_store
    barrier=Barrier(2);state=local()
    def synchronize(store_id):
        if not getattr(state,'entered',False):
            state.entered=True;barrier.wait(timeout=10)
        return original(store_id)
    monkeypatch.setattr(module,'lock_store',synchronize)
    def request(index):
        body={'request_key':'race-same' if same_key else f'race-{index}',
            'expected_version':version,
            'lines':[dict(shipment_item_id=line_id,checked_qty=30,sellable_qty=30,damaged_qty=0,short_qty=0)]}
        with committed_app.app_context():
            return _write(clients[index],'POST',f'/api/fulfillment/shipments/{shipment_id}/receipts',body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(request,i) for i in range(2)]
        responses=[f.result(timeout=20) for f in futures]
    assert sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409]),[r.json for r in responses]
    db.session.expire_all()
    stock=db.session.execute(db.select(Inventory).where(Inventory.store_id==store_id,Inventory.product_id==product_id)).scalar_one()
    assert stock.book_physical_qty==50
    assert db.session.execute(db.select(db.func.count(Receipt.id))).scalar_one()==1


@pytest.mark.parametrize('same_key',[True,False])
def test_two_shipments_cannot_exceed_original_commitment(committed_app,monkeypatch,same_key):
    client=committed_app.test_client()
    order,item,manager,cycle,run=real_order(committed_app,client)
    operator=db.session.execute(db.select(User).where(User.username=='operator')).scalar_one()
    eta=cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    fulfillment_service.accept(item_id=item.id,actor_id=operator.id,committed_qty=30,eta=eta,session=db.session)
    db.session.commit()
    order_id,item_id,version=order.id,item.id,order.version
    db.session.remove()
    clients=[committed_app.test_client(),committed_app.test_client()]
    for c in clients:
        with committed_app.app_context(): assert login(c,'operator').status_code==200
    import app.services.fulfillment_requests as module
    original=module.lock_store;barrier=Barrier(2);state=local()
    def synchronize(store_id):
        if not getattr(state,'entered',False):state.entered=True;barrier.wait(timeout=10)
        return original(store_id)
    monkeypatch.setattr(module,'lock_store',synchronize)
    def request(index):
        body={'request_key':'same-shipment' if same_key else f'shipment-{index}',
            'expected_version':version,
            'lines':[dict(item_id=item_id,quantity=30,eta=eta)]}
        with committed_app.app_context():
            return _write(clients[index],'POST',f'/api/fulfillment/orders/{order_id}/shipments',body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(request,i) for i in range(2)]
        responses=[f.result(timeout=20) for f in futures]
    assert sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409]),[r.json for r in responses]
    assert db.session.execute(db.select(db.func.sum(ShipmentItem.shipped_qty))).scalar_one()==30


def test_open_sources_read_commit_after_old_snapshot(committed_app):
    from sqlalchemy.orm import Session
    from app.models import OrderItem, Store
    from app.services.open_orders import open_orders_service
    from app.services.clock import business_now
    order,item,manager,cycle,run=real_order(committed_app,committed_app.test_client())
    operator=db.session.execute(db.select(User).where(User.username=='operator')).scalar_one()
    eta=cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    with Session(db.engine) as reader:
        assert reader.execute(db.select(OrderItem.status).where(OrderItem.id==item.id)).scalar_one()=='SUBMITTED'
        fulfillment_service.accept(item_id=item.id,actor_id=operator.id,committed_qty=30,eta=eta,session=db.session)
        db.session.commit()
        reader.execute(db.select(Store).where(Store.id==order.store_id).with_for_update()).scalar_one()
        result=open_orders_service.get_open_orders(store_id=order.store_id,baseline_at=run.baseline_at,
            protection_end=run.protection_end,evaluated_at=business_now(),session=reader)
        source=next(s for s in result.sources if s.product_id==item.product_id)
        assert source.bucket=='C' and source.quantity==30
