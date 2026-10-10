from app.extensions import db
from .common import Entity, StoreItem, Versioned


class SalesImportBatch(Entity, db.Model):
    __tablename__ = 'sales_import_batches'
    __table_args__ = (db.UniqueConstraint('store_id', 'source_batch_id'),
        db.CheckConstraint("import_mode IN ('historical','daily_posting')", name='mode'))
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    source_batch_id = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    import_mode = db.Column(db.String(24), nullable=False)
    replaces_batch_id = db.Column(db.Integer, db.ForeignKey('sales_import_batches.id'))
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)


class SalesDaily(StoreItem, Versioned, db.Model):
    __tablename__ = 'sales_daily'
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id', 'business_date'),
        db.CheckConstraint('sold_qty >= 0', name='sold_qty'),)
    business_date = db.Column(db.Date, nullable=False)
    interval_start = db.Column(db.DateTime, nullable=False)
    interval_end = db.Column(db.DateTime, nullable=False)
    sold_qty = db.Column(db.Integer, nullable=False)
    was_stockout = db.Column(db.Boolean, nullable=False)
    is_open = db.Column(db.Boolean, nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('sales_import_batches.id'), nullable=False)
    import_mode = db.Column(db.String(24), nullable=False)
    applied_at = db.Column(db.DateTime)
    movement_id = db.Column(db.Integer, db.ForeignKey('inventory_movements.id'), unique=True)
    event_note = db.Column(db.String(500))


# Import evidence is append-only; corrections create a new batch.
from sqlalchemy import event, inspect, select
from app.services.errors import DomainError


@event.listens_for(SalesImportBatch, 'before_update')
def protect_import_batch(mapper, connection, target):
    # The insert reserves the batch ID inside the caller's transaction; seal its
    # pending snapshot once after real movements are known, before the outer commit.
    state = inspect(target)
    if not state.deleted:
        saved = connection.execute(select(SalesImportBatch.snapshot).where(
            SalesImportBatch.id == target.id)).scalar_one()
        changes = [attr.key for attr in state.attrs if attr.history.has_changes()]
        if (saved == {'pending': True} and changes == ['snapshot']
                and isinstance(target.snapshot, dict) and 'result' in target.snapshot
                and 'rows' in target.snapshot and 'input' in target.snapshot):
            return
    raise DomainError('IMMUTABLE_RECORD', '銷售原批次與提交快照不得覆寫；請新增更正批次', 409)


@event.listens_for(SalesImportBatch, 'before_delete')
def prevent_import_batch_delete(mapper, connection, target):
    raise DomainError('IMMUTABLE_RECORD', '銷售批次不得刪除；請新增更正批次', 409)
