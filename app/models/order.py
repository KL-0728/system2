from app.extensions import db
from .common import Entity, Versioned


class OrderDraft(Entity, Versioned, db.Model):
    __tablename__ = 'order_drafts'
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    cycle_id = db.Column(db.Integer, db.ForeignKey('delivery_cycles.id'), nullable=False)
    run_id = db.Column(db.Integer, db.ForeignKey('replenishment_runs.id'), nullable=False)
    status = db.Column(db.String(24), nullable=False, default='DRAFT')
    created_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)
    parent_order_id = db.Column(db.Integer, db.ForeignKey('orders.id', use_alter=True, name='fk_draft_parent_order'))
    additional_order_reason = db.Column(db.String(500))


class DraftItem(Entity, db.Model):
    __tablename__ = 'draft_items'
    __table_args__ = (db.UniqueConstraint('draft_id', 'product_id'),
        db.CheckConstraint('final_qty >= 0 AND final_qty <= 1000000', name='final_qty'))
    draft_id = db.Column(db.Integer, db.ForeignKey('order_drafts.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    run_item_id = db.Column(db.Integer, db.ForeignKey('run_items.id'), nullable=False)
    final_qty = db.Column(db.Integer, nullable=False)
    reason_code = db.Column(db.String(40))
    reason = db.Column(db.String(500))
    special_need = db.Column(db.JSON)
    manual_forecast_acknowledged = db.Column(db.Boolean, nullable=False, default=False)


class Order(Entity, Versioned, db.Model):
    __tablename__ = 'orders'
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    draft_id = db.Column(db.Integer, db.ForeignKey('order_drafts.id'), nullable=False, unique=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('delivery_cycles.id'), nullable=False)
    number = db.Column(db.String(64), nullable=False, unique=True)
    submitted_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(32), nullable=False, default='SUBMITTED')
    fixture_only = db.Column(db.Boolean, nullable=False, default=False)


class OrderItem(Entity, Versioned, db.Model):
    __tablename__ = 'order_items'
    __table_args__ = (db.UniqueConstraint('order_id', 'product_id'),
        db.CheckConstraint('original_qty > 0 AND original_qty <= 1000000', name='original_qty'),
        db.CheckConstraint('committed_qty >= 0 AND cancelled_qty >= 0 AND disputed_qty >= 0', name='fulfillment_qty'))
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    original_qty = db.Column(db.Integer, nullable=False)
    product_snapshot = db.Column(db.JSON, nullable=False)
    committed_qty = db.Column(db.Integer, nullable=False, default=0)
    cancelled_qty = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(32), nullable=False, default='SUBMITTED')
    eta = db.Column(db.DateTime)
    deduction_expires_at = db.Column(db.DateTime, nullable=False)
    commitment_disputed = db.Column(db.Boolean, nullable=False, default=False)
    disputed_qty = db.Column(db.Integer, nullable=False, default=0)


class OrderConfirmation(Entity, db.Model):
    __tablename__ = 'order_confirmations'
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), unique=True)
    draft_id = db.Column(db.Integer, db.ForeignKey('order_drafts.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    draft_version = db.Column(db.Integer, nullable=False)
    store_version = db.Column(db.Integer, nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    payload_hash = db.Column(db.String(64), nullable=False)
    text_version = db.Column(db.String(32), nullable=False)
    warning_version = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    risk_evaluated_at = db.Column(db.DateTime, nullable=False)
    acknowledged_at = db.Column(db.DateTime)
    order_acknowledged = db.Column(db.Boolean, nullable=False, default=False)
    exception_acknowledgements = db.Column(db.JSON, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)


class SubmissionKey(Entity, db.Model):
    __tablename__ = 'submission_keys'
    __table_args__ = (db.UniqueConstraint('user_id', 'store_id', 'key'),)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
