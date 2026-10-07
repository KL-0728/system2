from app.extensions import db
from .common import Entity, Versioned


class OperationalTask(Entity, Versioned, db.Model):
    __tablename__ = 'operational_tasks'
    __table_args__ = (db.UniqueConstraint('store_id', 'source_type', 'source_id', 'task_type'),)
    store_id = db.Column(db.Integer, db.ForeignKey('stores.id'), nullable=False, index=True)
    owner_role = db.Column(db.String(24), nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(100), nullable=False)
    task_type = db.Column(db.String(40), nullable=False)
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_versions.id'), nullable=False)
    due_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False)
    completed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    completed_at = db.Column(db.DateTime)
    result = db.Column(db.JSON)
