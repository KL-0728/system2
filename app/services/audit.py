from uuid import uuid4
from flask import g, has_request_context
from app.extensions import db
from app.models.audit import AuditEvent
from app.services.clock import server_now, business_now, utc_naive


def record_event(actor_id, store_id, action, entity, old=None, new=None):
    event = AuditEvent(actor_id=actor_id, store_id=store_id, action=action, entity=entity,
        old=old, new=new, server_time=utc_naive(server_now()), business_time=utc_naive(business_now()),
        request_id=getattr(g, 'request_id', str(uuid4())) if has_request_context() else str(uuid4()))
    db.session.add(event)
    return event
