from app.extensions import db


class AuditEvent(db.Model):
    __tablename__ = 'audit_events'
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(80), nullable=False)
    entity = db.Column(db.String(120), nullable=False)
    old = db.Column(db.JSON)
    new = db.Column(db.JSON)
    server_time = db.Column(db.DateTime, nullable=False)
    business_time = db.Column(db.DateTime, nullable=False)
    request_id = db.Column(db.String(80), nullable=False)


class BusinessClock(db.Model):
    __tablename__ = 'business_clocks'
    id = db.Column(db.Integer, primary_key=True)
    business_anchor = db.Column(db.DateTime, nullable=False)
    server_anchor = db.Column(db.DateTime, nullable=False)
    paused = db.Column(db.Boolean, nullable=False, default=True)
