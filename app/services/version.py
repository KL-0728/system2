from contextlib import contextmanager
from app.extensions import db
from app.models.identity import Store
from app.services.errors import DomainError


def lock_store(store_id, expected_version=None):
    store = db.session.execute(db.select(Store).where(Store.id == store_id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
    if store is None:
        raise DomainError('NOT_FOUND', '門市不存在', 404)
    if expected_version is not None and store.calculation_version != expected_version:
        raise DomainError('VERSION_CONFLICT', '資料已更新，請重新核對', 409,
            {'current_version': store.calculation_version})
    return store


def bump_store(store):
    store.calculation_version += 1
    return store.calculation_version


@contextmanager
def transaction():
    # SQLAlchemy autobegin may already contain authentication reads.
    # Only the outer route/CLI entry may call this helper.
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
