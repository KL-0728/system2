from app.extensions import db
from .common import Entity, Versioned


class SupplyChangeRequest(Entity, Versioned, db.Model):
    __tablename__ = 'supply_change_requests'
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'), nullable=False, index=True)
    old_conditions = db.Column(db.JSON, nullable=False)
    new_conditions = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    response_due_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='PENDING')
    responded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    responded_at = db.Column(db.DateTime)
    response = db.Column(db.JSON)


class Shipment(Entity, Versioned, db.Model):
    __tablename__ = 'shipments'
    __table_args__ = (db.UniqueConstraint('order_id', 'request_key'),)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    shipped_at = db.Column(db.DateTime, nullable=False)


class ShipmentItem(Entity, Versioned, db.Model):
    __tablename__ = 'shipment_items'
    __table_args__ = (db.UniqueConstraint('shipment_id', 'order_item_id', 'kind'),
        db.CheckConstraint('shipped_qty > 0 AND checked_qty >= 0 AND checked_qty <= shipped_qty', name='quantities'),
        db.CheckConstraint("(kind = 'original' AND authorization_id IS NULL) OR (kind = 'replacement' AND authorization_id IS NOT NULL)", name='kind_authorization'))
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id'), nullable=False)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'), nullable=False)
    kind = db.Column(db.String(24), nullable=False)
    authorization_id = db.Column(db.Integer, db.ForeignKey('replacement_authorizations.id', use_alter=True, name='fk_shipment_authorization'))
    shipped_qty = db.Column(db.Integer, nullable=False)
    checked_qty = db.Column(db.Integer, nullable=False, default=0)
    eta = db.Column(db.DateTime, nullable=False)
    eta_disputed = db.Column(db.Boolean, nullable=False, default=False)


class Receipt(Entity, db.Model):
    __tablename__ = 'receipts'
    __table_args__ = (db.UniqueConstraint('store_id', 'user_id', 'shipment_id', 'request_key'),)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipments.id'), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False)


class ReceiptItem(Entity, db.Model):
    __tablename__ = 'receipt_items'
    __table_args__ = (db.UniqueConstraint('receipt_id', 'shipment_item_id'),
        db.CheckConstraint('checked_qty > 0 AND sellable_qty >= 0 AND damaged_qty >= 0 AND short_qty >= 0 AND checked_qty = sellable_qty + damaged_qty + short_qty', name='quantities'))
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id'), nullable=False)
    shipment_item_id = db.Column(db.Integer, db.ForeignKey('shipment_items.id'), nullable=False)
    checked_qty = db.Column(db.Integer, nullable=False)
    sellable_qty = db.Column(db.Integer, nullable=False)
    damaged_qty = db.Column(db.Integer, nullable=False)
    short_qty = db.Column(db.Integer, nullable=False)
    inventory_source_id = db.Column(db.String(100), nullable=False, unique=True)
    note = db.Column(db.String(500))


class ReceiptVariance(Entity, Versioned, db.Model):
    __tablename__ = 'receipt_variances'
    __table_args__ = (db.UniqueConstraint('receipt_item_id', 'kind'),
        db.CheckConstraint('quantity > 0 AND closed_qty >= 0 AND closed_qty <= quantity', name='quantities'))
    receipt_item_id = db.Column(db.Integer, db.ForeignKey('receipt_items.id'), nullable=False)
    parent_variance_id = db.Column(db.Integer, db.ForeignKey('receipt_variances.id'))
    kind = db.Column(db.String(24), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    closed_qty = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(24), nullable=False, default='OPEN')
    created_at = db.Column(db.DateTime, nullable=False)
    resolved_at = db.Column(db.DateTime)
    resolution = db.Column(db.JSON)


class ReplacementAuthorization(Entity, Versioned, db.Model):
    __tablename__ = 'replacement_authorizations'
    __table_args__ = (db.UniqueConstraint('variance_id', 'request_key'),
        db.CheckConstraint('authorized_qty > 0 AND used_qty >= 0 AND closed_qty >= 0 AND used_qty + closed_qty <= authorized_qty', name='quantities'))
    variance_id = db.Column(db.Integer, db.ForeignKey('receipt_variances.id'), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    authorized_qty = db.Column(db.Integer, nullable=False)
    used_qty = db.Column(db.Integer, nullable=False, default=0)
    closed_qty = db.Column(db.Integer, nullable=False, default=0)
    eta = db.Column(db.DateTime, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)


class FulfillmentEvent(Entity, db.Model):
    __tablename__ = 'fulfillment_events'
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    source_key = db.Column(db.String(100), nullable=False, unique=True)
    event_type = db.Column(db.String(40), nullable=False)
    occurred_at = db.Column(db.DateTime, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
