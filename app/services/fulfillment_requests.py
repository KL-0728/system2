"""HTTP preconditions for D writes; successful idempotent retries win first."""
from flask import current_app
from app.extensions import db
from app.models import (Order, OrderItem, Shipment, ShipmentItem, Receipt, ReceiptItem,
    ReceiptVariance, SupplyChangeRequest, ReplacementAuthorization, FulfillmentEvent)
from app.services.access import authorize_store
from app.services.errors import DomainError
from app.services.version import lock_store


def check_precondition(actor, method, ids, body, session):
    paths = {
        'order_id': [(Order, None)],
        'item_id': [(OrderItem, 'order_id'), (Order, None)],
        'shipment_id': [(Shipment, 'order_id'), (Order, None)],
        'shipment_item_id': [(ShipmentItem, 'order_item_id'), (OrderItem, 'order_id'), (Order, None)],
        'change_id': [(SupplyChangeRequest, 'order_item_id'), (OrderItem, 'order_id'), (Order, None)],
        'variance_id': [(ReceiptVariance, 'receipt_item_id'), (ReceiptItem, 'shipment_item_id'),
            (ShipmentItem, 'order_item_id'), (OrderItem, 'order_id'), (Order, None)],
        'event_id': [(FulfillmentEvent, 'order_item_id'), (OrderItem, 'order_id'), (Order, None)],
    }
    key, identity = next(iter(ids.items()))
    for model, field in paths[key]:
        row = session.get(model, identity)
        if row is None:
            raise DomainError('NOT_FOUND', '履約資料不存在', 404)
        if field:
            identity = getattr(row, field)
    order = row
    authorize_store(actor, order.store_id)
    if order.fixture_only and current_app.config['APP_ENV'] != 'test' and current_app.config['MODULE_DEV'] != 'D':
        raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
    lock_store(order.store_id)
    order = session.execute(db.select(Order).where(Order.id == order.id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one()
    request_key = body.get('request_key')
    previous = None
    if isinstance(request_key, str):
        query = None
        if method == 'ship':
            query = db.select(Shipment).where(Shipment.order_id == order.id, Shipment.request_key == request_key)
        elif method == 'receive':
            query = db.select(Receipt).where(Receipt.shipment_id == ids['shipment_id'],
                Receipt.user_id == actor.id, Receipt.request_key == request_key)
        elif method == 'authorize_replacement':
            query = db.select(ReplacementAuthorization).where(
                ReplacementAuthorization.variance_id == ids['variance_id'], ReplacementAuthorization.request_key == request_key)
        elif method in ('remove_damaged', 'report_extra'):
            source = f"damaged:{ids['variance_id']}:{request_key}" if method == 'remove_damaged' else \
                f"extra:{ids['shipment_id']}:{request_key}"
            query = db.select(FulfillmentEvent).where(FulfillmentEvent.source_key == source)
        if query is not None:
            previous = session.execute(query.with_for_update()).scalar_one_or_none()
    expected = body.pop('expected_version', None)
    if previous is not None:
        # D's method still verifies original payload and returns its saved result.
        return
    if type(expected) is not int or expected < 1:
        raise DomainError('INVALID_VERSION', '請重新載入履約資料後操作', 422)
    if order.version != expected:
        raise DomainError('VERSION_CONFLICT', '供貨或收貨資料已更新，請重新整理並核對', 409,
            {'current_version':order.version, 'order_id':order.id})
