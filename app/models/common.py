from app.extensions import db


class Entity:
    id = db.Column(db.Integer, primary_key=True)


class StoreItem(Entity):
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)


class Versioned:
    version = db.Column(db.Integer, nullable=False, default=1)
