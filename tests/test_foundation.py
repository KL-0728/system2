from datetime import timedelta, datetime, timezone
from decimal import Decimal
import pytest
from app.config import settings, validate_database
from app.extensions import db
from app.models import Store, User, AuditEvent, BusinessClock, Inventory
from app.services.clock import business_now, set_clock, round_window, utc_naive
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


@pytest.mark.parametrize('minutes', [0, 1, 2])
def test_b_demo_accepts_seed_start_and_preserves_later_progress(seeded, monkeypatch, minutes):
    # Only the CLI guard's DB label is controlled; SQL stays on the isolated test connection.
    connection = db.engine
    monkeypatch.setattr(connection, 'url',
        connection.engine.url.set(database='system2_b_synthetic_demo'), raising=False)
    monkeypatch.setitem(seeded.config, 'APP_ENV', 'demo')
    monkeypatch.setitem(seeded.config, 'MODULE_DEV', 'B')
    baseline = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    start = baseline + timedelta(minutes=minutes)
    db.session.get(BusinessClock, 1).business_anchor = utc_naive(start)
    db.session.flush()
    result = seeded.test_cli_runner().invoke(args=['inventory', 'prepare-demo'])
    assert result.exit_code == 0, result.output
    expected = baseline + timedelta(days=1, minutes=20) if minutes < 2 else start
    assert business_now() == expected
    assert all(stock.counted_at == utc_naive(baseline) and stock.book_physical_qty == 20
        for stock in db.session.execute(db.select(Inventory)).scalars())
    again = seeded.test_cli_runner().invoke(args=['inventory', 'prepare-demo'])
    assert again.exit_code == 0 and business_now() == expected
