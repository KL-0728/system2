"""D integration checks against the project's isolated MySQL test transaction."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import (BusinessClock, DeliveryCycle, Inventory, User,
    ShipmentItem, ReceiptVariance, Product)
from app.providers import get_provider, register_provider
from app.services.clock import aware, business_now
from app.services.errors import DomainError
from app.services.fulfillment import fulfillment_service
from app.services.open_orders import open_orders_service
from app.testing.factories import make_order


def _actor(name):
    return db.session.execute(db.select(User).where(User.username == name)).scalar_one()


def _case():
    order, item = make_order(db.session, quantity=5)
    operator = _actor('operator')
    manager = _actor('manager1')
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor += timedelta(minutes=1)
    db.session.flush()
    eta = aware(db.session.get(DeliveryCycle, order.cycle_id).arrival_at).isoformat()
    return order, item, operator, manager, eta


def test_fixture_order_cannot_be_mutated_in_formal_mode(seeded):
    order, item, operator, manager, eta = _case()
    assert order.fixture_only
    old_environment = seeded.config['APP_ENV']
    old_module = seeded.config['MODULE_DEV']
    try:
        seeded.config['APP_ENV'] = 'demo'
        seeded.config['MODULE_DEV'] = ''
        with pytest.raises(DomainError) as caught:
            fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
                committed_qty=5, eta=eta, session=db.session)
        assert caught.value.code == 'NOT_FOUND'
    finally:
        seeded.config['APP_ENV'] = old_environment
        seeded.config['MODULE_DEV'] = old_module
        db.session.rollback()


def test_partial_receipt_and_idempotent_inventory(seeded):
    order, item, operator, manager, eta = _case()
    inventory = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    before = inventory.book_physical_qty
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    shipment = fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='ship-once', lines=[dict(item_id=item.id, quantity=5,
            eta=eta)], session=db.session)
    line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == shipment.id)).scalar_one()
    payload = [dict(shipment_item_id=line.id, checked_qty=2,
        sellable_qty=2, damaged_qty=0, short_qty=0)]
    receipt = fulfillment_service.receive(shipment_id=shipment.id,
        actor_id=manager.id, request_key='receipt-once', lines=payload,
        session=db.session)
    assert line.checked_qty == 2
    assert inventory.book_physical_qty == before + 2
    assert fulfillment_service.receive(shipment_id=shipment.id,
        actor_id=manager.id, request_key='receipt-once', lines=payload,
        session=db.session).id == receipt.id
    assert inventory.book_physical_qty == before + 2
    with pytest.raises(DomainError, match='相同識別'):
        fulfillment_service.receive(shipment_id=shipment.id,
            actor_id=manager.id, request_key='receipt-once', lines=[dict(
                shipment_item_id=line.id, checked_qty=1,
                sellable_qty=1, damaged_qty=0, short_qty=0)],
            session=db.session)
    db.session.rollback()


def test_damaged_receipt_stays_out_of_sellable_and_excess_rejected(seeded):
    order, item, operator, manager, eta = _case()
    inventory = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    physical, unsellable = inventory.book_physical_qty, inventory.book_unsellable_qty
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    shipment = fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='damaged-ship', lines=[dict(item_id=item.id, quantity=5,
            eta=eta)], session=db.session)
    line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == shipment.id)).scalar_one()
    fulfillment_service.receive(shipment_id=shipment.id,
        actor_id=manager.id, request_key='damaged-receipt', lines=[dict(
            shipment_item_id=line.id, checked_qty=5, sellable_qty=3,
            damaged_qty=2, short_qty=0, note='包裝破損')], session=db.session)
    assert inventory.book_physical_qty == physical + 5
    assert inventory.book_unsellable_qty == unsellable + 2
    with pytest.raises(DomainError):
        fulfillment_service.receive(shipment_id=shipment.id,
            actor_id=manager.id, request_key='too-much', lines=[dict(
                shipment_item_id=line.id, checked_qty=1, sellable_qty=1,
                damaged_qty=0, short_qty=0)], session=db.session)
    db.session.rollback()


def test_failed_inventory_writer_rolls_back_receipt(seeded):
    order, item, operator, manager, eta = _case()
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    shipment = fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='failure-ship', lines=[dict(item_id=item.id, quantity=5,
            eta=eta)], session=db.session)
    line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == shipment.id)).scalar_one()

    class FailingWriter:
        def apply_movement(self, **kwargs):
            raise DomainError('TEST_FAILURE', '受控寫入失敗', 409)

    real = get_provider('inventory_writer')
    register_provider('inventory_writer', FailingWriter(), test_only=True)
    try:
        with pytest.raises(DomainError) as caught:
            fulfillment_service.receive(shipment_id=shipment.id,
                actor_id=manager.id, request_key='failure-receipt', lines=[dict(
                    shipment_item_id=line.id, checked_qty=5, sellable_qty=5,
                    damaged_qty=0, short_qty=0)], session=db.session)
        assert caught.value.code == 'TEST_FAILURE'
        db.session.rollback()
    finally:
        register_provider('inventory_writer', real)
    # A separate test with two real connections must verify the production
    # transaction and lock behavior once a dedicated MySQL test DB is ready.


def test_open_source_moves_from_pending_to_shipment_once(seeded):
    order, item, operator, manager, eta = _case()
    order.fixture_only = False  # test-only formal source; not a C submission claim
    cycle = db.session.get(DeliveryCycle, order.cycle_id)
    baseline = aware(cycle.baseline_at)
    end = baseline + timedelta(days=2)

    def sources():
        return open_orders_service.get_open_orders(store_id=order.store_id,
            baseline_at=baseline, protection_end=end,
            evaluated_at=business_now(), session=db.session).sources

    assert [(s.bucket, s.quantity) for s in sources()] == [('U', 5)]
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    assert [(s.bucket, s.quantity) for s in sources()] == [('C', 5)]
    shipment = fulfillment_service.ship(order_id=order.id,
        actor_id=operator.id, request_key='source-ship',
        lines=[dict(item_id=item.id, quantity=5, eta=eta)], session=db.session)
    assert [(s.source_type, s.quantity) for s in sources()] == [('shipment', 5)]
    line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == shipment.id)).scalar_one()
    fulfillment_service.receive(shipment_id=shipment.id, actor_id=manager.id,
        request_key='source-receipt', lines=[dict(shipment_item_id=line.id,
            checked_qty=2, sellable_qty=2, damaged_qty=0, short_qty=0)],
        session=db.session)
    assert [(s.source_type, s.quantity) for s in sources()] == [('shipment', 3)]
    db.session.rollback()


def test_damaged_replacement_uses_separate_authorized_quota(seeded):
    order, item, operator, manager, eta = _case()
    inventory = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    start_h = inventory.book_physical_qty - inventory.book_unsellable_qty
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    original = fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='original-five', lines=[dict(item_id=item.id, quantity=5,
            eta=eta)], session=db.session)
    line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == original.id)).scalar_one()
    fulfillment_service.receive(shipment_id=original.id, actor_id=manager.id,
        request_key='original-receipt', lines=[dict(shipment_item_id=line.id,
            checked_qty=5, sellable_qty=3, damaged_qty=2, short_qty=0,
            note='破損')], session=db.session)
    variance = db.session.execute(db.select(ReceiptVariance).order_by(
        ReceiptVariance.id.desc())).scalars().first()
    auth = fulfillment_service.authorize_replacement(variance_id=variance.id,
        actor_id=operator.id, request_key='replace-two', quantity_value=2,
        eta=eta, session=db.session)
    with pytest.raises(DomainError):
        fulfillment_service.authorize_replacement(variance_id=variance.id,
            actor_id=operator.id, request_key='replace-again',
            quantity_value=1, eta=eta, session=db.session)
    replacement = fulfillment_service.ship(order_id=order.id,
        actor_id=operator.id, request_key='replacement-two',
        lines=[dict(item_id=item.id, kind='replacement',
            authorization_id=auth.id, quantity=2, eta=eta)], session=db.session)
    replacement_line = db.session.execute(db.select(ShipmentItem).where(
        ShipmentItem.shipment_id == replacement.id)).scalar_one()
    fulfillment_service.receive(shipment_id=replacement.id,
        actor_id=manager.id, request_key='replacement-receipt',
        lines=[dict(shipment_item_id=replacement_line.id, checked_qty=2,
            sellable_qty=2, damaged_qty=0, short_qty=0)], session=db.session)
    assert inventory.book_physical_qty - inventory.book_unsellable_qty == start_h + 5
    fulfillment_service.close_variance(variance_id=variance.id,
        actor_id=operator.id, reason='補送完成', session=db.session)
    db.session.rollback()


def test_manager_cancellation_requires_operator_and_dispute_blocks_shipping(seeded):
    order, item, operator, manager, eta = _case()
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    change = fulfillment_service.request_cancel(item_id=item.id,
        actor_id=manager.id, reason='門市需求改變', session=db.session)
    with pytest.raises(DomainError) as caught:
        fulfillment_service.respond_change(change_id=change.id,
            actor_id=manager.id, accept=False, reason='自己回覆', session=db.session)
    assert caught.value.code == 'FORBIDDEN'
    fulfillment_service.respond_change(change_id=change.id,
        actor_id=operator.id, accept=False, reason='已備貨', session=db.session)
    with pytest.raises(DomainError) as caught:
        fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
            request_key='blocked-shipment', lines=[dict(item_id=item.id,
                quantity=1, eta=eta)], session=db.session)
    assert caught.value.code == 'INVALID_STATE'
    fulfillment_service.reaffirm(item_id=item.id, actor_id=operator.id,
        session=db.session)
    fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='unblocked-shipment', lines=[dict(item_id=item.id,
            quantity=1, eta=eta)], session=db.session)
    db.session.rollback()


def test_extra_delivery_is_recorded_without_inventory_credit(seeded):
    order, item, operator, manager, eta = _case()
    product = db.session.execute(db.select(Product).where(
        Product.id != item.product_id).order_by(Product.id)).scalars().first()
    stock = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == order.store_id,
        Inventory.product_id == product.id)).scalar_one()
    before = stock.book_physical_qty
    fulfillment_service.accept(item_id=item.id, actor_id=operator.id,
        committed_qty=5, eta=eta, session=db.session)
    shipment = fulfillment_service.ship(order_id=order.id, actor_id=operator.id,
        request_key='extra-anchor', lines=[dict(item_id=item.id,
            quantity=1, eta=eta)], session=db.session)
    case = fulfillment_service.report_extra(shipment_id=shipment.id,
        actor_id=manager.id, request_key='extra-one', product_id=product.id,
        quantity_value=1, reason='送錯商品', session=db.session)
    assert stock.book_physical_qty == before
    assert fulfillment_service.report_extra(shipment_id=shipment.id,
        actor_id=manager.id, request_key='extra-one', product_id=product.id,
        quantity_value=1, reason='送錯商品', session=db.session).id == case.id
    fulfillment_service.resolve_extra(event_id=case.id, actor_id=operator.id,
        action='return', reason='退回統家', session=db.session)
    assert stock.book_physical_qty == before
    db.session.rollback()
