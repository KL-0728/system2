from functools import wraps
from flask import g, session
from app.extensions import db
from app.models.identity import User, Store
from app.services.errors import DomainError


def load_user():
    g.user = db.session.get(User, session['user_id']) if session.get('user_id') else None
    if g.user and not g.user.active:
        session.clear()
        g.user = None


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                raise DomainError('UNAUTHENTICATED', '請先登入', 401)
            if roles and g.user.role not in roles:
                raise DomainError('FORBIDDEN', '無此操作權限', 403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def authorize_store(actor, store_id, roles=('manager', 'operator', 'admin')):
    if not actor or not actor.active or actor.role not in roles:
        raise DomainError('FORBIDDEN', '無此操作權限', 403)
    store = db.session.get(Store, store_id)
    if not store or not store.active or (actor.role == 'manager' and store not in actor.stores):
        raise DomainError('NOT_FOUND', '門市不存在或不可存取', 404)
    return store
