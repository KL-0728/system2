from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from datetime import time
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.extensions import db
from app.models import Store, OrderItem, InventoryCount, ShipmentItem
from app.testing.factories import make_order
from app.services.errors import DomainError
from app.services.version import lock_store, bump_store


def test_real_mysql_store_lock_serializes_stale_writers(app):
    # Separate connections + committed isolated test-owned store, no fixture visibility shortcut.
    engine = app.extensions['sqlalchemy']._app_engines[app][None].engine
    # Fixture engine is a Connection; its .engine is the independent connection pool.
    code = 'LOCK-' + uuid4().hex[:12]
    with engine.begin() as connection:
        result = connection.execute(Store.__table__.insert().values(code=code, name='併發測試專用',
            timezone='Asia/Taipei', cutoff=time(22), active=True, calculation_version=1))
        store_id = result.inserted_primary_key[0]
    locked, attempted = Event(), Event()

    def first():
        with engine.begin() as connection:
            version = connection.execute(text('SELECT calculation_version FROM stores WHERE id=:id FOR UPDATE'), {'id': store_id}).scalar_one()
            locked.set()
            assert attempted.wait(5)
            connection.execute(text('UPDATE stores SET calculation_version=:v WHERE id=:id'), {'id':store_id,'v':version+1})

    def second():
        assert locked.wait(5)
        attempted.set()
        with engine.begin() as connection:
            return connection.execute(text('SELECT calculation_version FROM stores WHERE id=:id FOR UPDATE'), {'id': store_id}).scalar_one()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future1, future2 = pool.submit(first), pool.submit(second)
            future1.result(timeout=10)
            assert future2.result(timeout=10) == 2
    finally:
        with engine.begin() as connection:
            connection.execute(Store.__table__.delete().where(Store.id == store_id, Store.code == code))


def test_fk_engine_and_snapshot_guard(seeded):
    engines = db.session.execute(text('SELECT DISTINCT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE="BASE TABLE"')).scalars().all()
    assert engines == ['InnoDB']
    foreign_keys = db.session.execute(text('SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE()')).scalars().all()
    assert 'fk_shipment_authorization' in foreign_keys and 'fk_draft_parent_order' in foreign_keys
    order, item = make_order(db.session)
    nested = db.session.begin_nested()
    item.original_qty = 1000
    with pytest.raises(DomainError) as exc:
        db.session.flush()
    nested.rollback()
    assert exc.value.code == 'IMMUTABLE_RECORD'
    db.session.expire_all()
    assert item.original_qty == 30
    from app.models import OrderConfirmation
    confirmation = db.session.execute(db.select(OrderConfirmation).where(OrderConfirmation.order_id == order.id)).scalar_one()
    nested = db.session.begin_nested()
    confirmation.snapshot = {'tampered': True}
    with pytest.raises(DomainError):
        db.session.flush()
    nested.rollback()
