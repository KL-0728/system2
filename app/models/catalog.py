from app.extensions import db


class Product(db.Model):
    __tablename__ = 'products'
    __table_args__ = (db.CheckConstraint('pack_size > 0', name='pack_size'),)
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    base_unit = db.Column(db.String(16), nullable=False, default='件')
    pack_size = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)


class PolicyVersion(db.Model):
    __tablename__ = 'policy_versions'
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    effective_at = db.Column(db.DateTime, nullable=False)
    parameters = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id', 'version'),)


class StoreProduct(db.Model):
    __tablename__ = 'store_products'
    __table_args__ = (db.UniqueConstraint('store_id', 'product_id'),
        db.CheckConstraint('lead_days >= 1 AND safety_stock >= 0 AND capacity >= 0', name='policy_quantities'))
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_versions.id'), nullable=False)
    lead_days = db.Column(db.Integer, nullable=False, default=1)
    safety_stock = db.Column(db.Integer, nullable=False, default=10)
    capacity = db.Column(db.Integer, nullable=False, default=100)
    active = db.Column(db.Boolean, nullable=False, default=True)


class DeliveryCycle(db.Model):
    __tablename__ = 'delivery_cycles'
    __table_args__ = (db.UniqueConstraint('store_id', 'baseline_at', 'arrival_at'),)
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False)
    baseline_at = db.Column(db.DateTime, nullable=False)
    cutoff_at = db.Column(db.DateTime, nullable=False)
    arrival_at = db.Column(db.DateTime, nullable=False)
    cancelled = db.Column(db.Boolean, nullable=False, default=False)
