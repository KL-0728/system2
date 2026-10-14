"""Synthetic settled history costs; separate from real integration evidence."""
import subprocess
from time import perf_counter
from app.extensions import db
from app.models import OrderDraft, Order, OrderItem, Shipment, ShipmentItem
from app.services.clock import business_now
from app.services.open_orders import open_orders_service
from test_full_integration import real_order


def test_settled_history_result_matches_original_with_bounded_child_load(seeded, client):
    order, item, manager, cycle, run = real_order(seeded, client)
    drafts = [OrderDraft(store_id=order.store_id, user_id=manager.id, cycle_id=cycle.id,
        run_id=run.run_id, status='SUBMITTED', created_at=order.submitted_at, updated_at=order.submitted_at)
        for _ in range(1000)]
    db.session.add_all(drafts);db.session.flush()
    orders = [Order(store_id=order.store_id,user_id=manager.id,draft_id=d.id,cycle_id=cycle.id,
        number=f'HISTORY-CONTROLLED-{d.id}',submitted_at=order.submitted_at,status='RECEIVED',fixture_only=False) for d in drafts]
    db.session.add_all(orders);db.session.flush()
    items = [OrderItem(order_id=o.id,product_id=item.product_id,original_qty=30,committed_qty=30,
        product_snapshot=item.product_snapshot,status='RECEIVED',eta=cycle.arrival_at,
        deduction_expires_at=item.deduction_expires_at) for o in orders]
    db.session.add_all(items);db.session.flush()
    shipments = [Shipment(order_id=o.id,request_key='controlled-history',payload_hash='0'*64,
        actor_id=manager.id,shipped_at=order.submitted_at) for o in orders]
    db.session.add_all(shipments);db.session.flush()
    db.session.add_all([ShipmentItem(shipment_id=s.id,order_item_id=i.id,kind='original',
        shipped_qty=30,checked_qty=30,eta=cycle.arrival_at) for s,i in zip(shipments,items)])
    db.session.flush()
    # Exact original reader from the synchronized baseline, not a new approximation.
    original = subprocess.run(['git','show','eecc49d:app/services/open_orders.py'],capture_output=True,check=True).stdout.decode('utf-8')
    namespace = {};exec(compile(original,'original-open-orders','exec'),namespace)
    args = dict(store_id=order.store_id,baseline_at=run.baseline_at,protection_end=run.protection_end,
        evaluated_at=business_now(),session=db.session)
    before = perf_counter();expected = namespace['OpenOrdersService']().get_open_orders(**args);old_elapsed=perf_counter()-before
    db.session.expire_all()
    before = perf_counter();actual = open_orders_service.get_open_orders(**args);new_elapsed=perf_counter()-before
    assert actual == expected
    print(f'1000 controlled settled orders / identical real active sources: original={old_elapsed:.3f}s new={new_elapsed:.3f}s')
    # Structural cost evidence: only active parents are materialized and locked.
    from sqlalchemy import event
    executed=[]
    def capture(conn,cursor,statement,parameters,context,many):
        if 'FROM shipment_items' in statement and ' IN (' in statement:
            executed.append(parameters)
    event.listen(db.engine,'before_cursor_execute',capture)
    try: open_orders_service.get_open_orders(**args)
    finally: event.remove(db.engine,'before_cursor_execute',capture)
    assert executed and max(len(p) for p in executed) <= 10
