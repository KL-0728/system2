from app.extensions import db


class FulfillmentCommand(db.Model):
    __tablename__ = 'fulfillment_commands'
    __table_args__ = (db.UniqueConstraint('order_id', 'actor_id', 'request_key'),)
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    result_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
