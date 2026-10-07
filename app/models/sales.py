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
