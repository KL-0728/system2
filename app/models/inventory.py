from sqlalchemy import event, inspect
from app.services.errors import DomainError
from app.extensions import db
from .common import Entity, StoreItem, Versioned


class Inventory(StoreItem, Versioned, db.Model):
    __tablename__ = 'inventories'
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id'),
        db.CheckConstraint('physical_qty >= 0 AND unsellable_qty >= 0 AND unsellable_qty <= physical_qty', name='count_quantities'))
    physical_qty = db.Column(db.Integer, nullable=False)
    unsellable_qty = db.Column(db.Integer, nullable=False, default=0)
    book_physical_qty = db.Column(db.Integer, nullable=False)
    book_unsellable_qty = db.Column(db.Integer, nullable=False, default=0)
    reconciliation_required = db.Column(db.Boolean, nullable=False, default=False)
    counted_at = db.Column(db.DateTime, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False)


class InventoryMovement(StoreItem, db.Model):
    __tablename__ = 'inventory_movements'
    __table_args__ = (db.UniqueConstraint('store_id', 'source_type', 'source_id', 'product_id'),)
    physical_delta = db.Column(db.Integer, nullable=False)
    unsellable_delta = db.Column(db.Integer, nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    occurred_at = db.Column(db.DateTime, nullable=False)
    applied_at = db.Column(db.DateTime, nullable=False)
    resulting_version = db.Column(db.Integer, nullable=False)


class InventoryCount(StoreItem, Versioned, db.Model):
    __tablename__ = 'inventory_counts'
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id', 'cutoff_at'),)
    cutoff_at = db.Column(db.DateTime, nullable=False)
    baseline_physical_qty = db.Column(db.Integer, nullable=False)
    baseline_unsellable_qty = db.Column(db.Integer, nullable=False)


class InventoryCountRevision(Entity, db.Model):
    __tablename__ = 'inventory_count_revisions'
    __table_args__ = (db.UniqueConstraint('count_id', 'revision'),
        db.CheckConstraint('physical_qty >= 0 AND unsellable_qty >= 0 AND unsellable_qty <= physical_qty', name='quantities'),)
    count_id = db.Column(db.Integer, db.ForeignKey('inventory_counts.id'), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    physical_qty = db.Column(db.Integer, nullable=False)
    unsellable_qty = db.Column(db.Integer, nullable=False)
    physical_delta = db.Column(db.Integer, nullable=False)
    unsellable_delta = db.Column(db.Integer, nullable=False)
    expected_version = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False)
    movement_id = db.Column(db.Integer, db.ForeignKey('inventory_movements.id'), nullable=False, unique=True)


class CountSubmissionKey(Entity, db.Model):
    __tablename__ = 'count_submission_keys'
    __table_args__ = (db.UniqueConstraint('store_id', 'user_id', 'request_key'),)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    revision_id = db.Column(db.Integer, db.ForeignKey('inventory_count_revisions.id'), nullable=False)


class InventoryReconciliation(StoreItem, Versioned, db.Model):
    __tablename__ = 'inventory_reconciliations'
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id', 'source_type', 'source_id'),)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(24), nullable=False, default='OPEN')
    created_at = db.Column(db.DateTime, nullable=False)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolution = db.Column(db.JSON)


# Count identity and its original 21:00 book baseline never change on revision.


@event.listens_for(InventoryCount, 'before_update')
def protect_count_baseline(mapper, connection, target):
    state = inspect(target)
    fields = ('store_id', 'product_id', 'cutoff_at', 'baseline_physical_qty', 'baseline_unsellable_qty')
    if any(state.attrs[field].history.has_changes() for field in fields):
        raise DomainError('IMMUTABLE_RECORD', '盤點原始帳面基準不得覆寫；請新增修訂', 409)


@event.listens_for(InventoryCount, 'before_delete')
@event.listens_for(CountSubmissionKey, 'before_delete')
@event.listens_for(CountSubmissionKey, 'before_update')
def protect_count_source(mapper, connection, target):
    raise DomainError('IMMUTABLE_RECORD', '盤點主紀錄與冪等來源不得改寫或刪除', 409)
