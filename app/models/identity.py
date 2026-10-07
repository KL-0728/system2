from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class Store(db.Model):
    __tablename__ = 'stores'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    timezone = db.Column(db.String(40), nullable=False, default='Asia/Taipei')
    cutoff = db.Column(db.Time, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    calculation_version = db.Column(db.Integer, nullable=False, default=1)


user_stores = db.Table('user_stores',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('store_id', db.Integer, db.ForeignKey('stores.id'), primary_key=True))


class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = (db.CheckConstraint("role IN ('manager','operator','admin')", name='role'),)
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    stores = db.relationship(Store, secondary=user_stores)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserAcknowledgement(db.Model):
    __tablename__ = 'user_acknowledgements'
    __table_args__ = (db.UniqueConstraint('user_id', 'text_version'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text_version = db.Column(db.String(32), nullable=False)
    acknowledged_at = db.Column(db.DateTime, nullable=False)
