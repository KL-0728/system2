from app.extensions import db
from .common import Entity, StoreItem, Versioned


class ManualForecastOverride(StoreItem, Versioned, db.Model):
    __tablename__ = 'manual_forecast_overrides'
    __table_args__ = (db.CheckConstraint('daily_demand >= 0 AND daily_demand <= 1000000', name='demand'),)
    daily_demand = db.Column(db.Numeric(16, 3), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)


class ReplenishmentRun(Entity, db.Model):
    __tablename__ = 'replenishment_runs'
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey('delivery_cycles.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_version = db.Column(db.Integer, nullable=False)
    baseline_at = db.Column(db.DateTime, nullable=False)
    actual_generated_at = db.Column(db.DateTime, nullable=False)
    data_through_at = db.Column(db.DateTime, nullable=False)
    risk_evaluated_at = db.Column(db.DateTime, nullable=False)
    model_version = db.Column(db.String(40), nullable=False)
    warning_version = db.Column(db.String(16), nullable=False)
    calculation_mode = db.Column(db.String(32), nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)


class RunItem(Entity, db.Model):
    __tablename__ = 'run_items'
    __table_args__ = (db.UniqueConstraint('run_id', 'product_id'),
        db.CheckConstraint('suggested_qty IS NULL OR (suggested_qty >= 0 AND suggested_qty <= 1000000)', name='suggested_qty'))
    run_id = db.Column(db.Integer, db.ForeignKey('replenishment_runs.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    mode = db.Column(db.String(32), nullable=False)
    mu = db.Column(db.Numeric(24, 12))
    target_stock = db.Column(db.Numeric(24, 12))
    raw_qty = db.Column(db.Numeric(24, 12))
    suggested_qty = db.Column(db.Integer)
    input_snapshot = db.Column(db.JSON, nullable=False)
    output_snapshot = db.Column(db.JSON, nullable=False)
    warnings = db.Column(db.JSON, nullable=False)
