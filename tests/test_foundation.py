from datetime import timedelta, datetime, timezone
from decimal import Decimal
import pytest
from app.config import settings, validate_database
from app.extensions import db
from app.models import Store, User, AuditEvent
from app.services.clock import business_now, set_clock, round_window
from app.services.version import lock_store, bump_store
from app.services.errors import DomainError


def test_guards(monkeypatch):
    for url, env in [('sqlite:///test.db', 'test'),
            ('mysql+pymysql://x@localhost/system2_a_demo', 'test'),
            ('mysql+pymysql://x@remote/system2_a_test', 'test')]:
        with pytest.raises(ValueError):
            validate_database(url, env)
    with pytest.raises(ValueError):
        settings({'APP_ENV': 'production', 'MODULE_DEV': 'B',
            'SECRET_KEY': 'x' * 32, 'SQLALCHEMY_DATABASE_URI': 'mysql+pymysql://x@localhost/prod'})


def test_version_clock_and_audit(seeded):
    store = db.session.execute(db.select(Store)).scalars().first()
    row = lock_store(store.id, 1)
    assert bump_store(row) == 2
    db.session.flush()
    with pytest.raises(DomainError) as conflict:
        lock_store(store.id, 1)
    assert conflict.value.status == 409
    admin = db.session.execute(db.select(User).where(User.role == 'admin')).scalar_one()
    start = business_now()
    set_clock(admin, start + timedelta(hours=1))
    db.session.flush()
    assert business_now() == start + timedelta(hours=1)
    with pytest.raises(DomainError):
        set_clock(admin, start)
    event = db.session.execute(db.select(AuditEvent)).scalar_one()
    assert event.server_time != event.business_time
    seeded.config['APP_ENV'] = 'production'
    with pytest.raises(DomainError):
        set_clock(admin, start + timedelta(days=1))


def test_decimal_and_round(seeded):
    assert seeded.json.loads(seeded.json.dumps({'mu': Decimal('20.125'), 'q': None})) == {'mu': '20.125', 'q': None}
    with pytest.raises(ValueError):
        seeded.json.dumps(Decimal('NaN'))
    b, cutoff = round_window(datetime(2026, 10, 8, 13, 40, tzinfo=timezone.utc))
    assert b.hour == 13 and b.minute == 0 and cutoff.hour == 14
