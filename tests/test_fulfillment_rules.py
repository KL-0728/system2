"""Rules that can run before an independent MySQL test database is available."""
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts import OpenOrdersDTO, OpenSourceDTO
from app.services.errors import DomainError
from app.services.fulfillment import _time
from app.services.open_orders import _bucket


UTC = timezone.utc
BASE = datetime(2026, 10, 8, 13, tzinfo=UTC)


def test_pending_expires_without_auto_cancellation():
    eta = BASE + timedelta(days=1)
    assert _bucket(eta, BASE + timedelta(minutes=60), False,
        BASE, eta, BASE) == 'U'
    assert _bucket(eta, BASE + timedelta(minutes=60), False,
        BASE, eta, BASE + timedelta(minutes=60)) == 'RISK'


def test_disputed_committed_and_late_shipment_are_not_effective():
    eta = BASE + timedelta(days=1)
    assert _bucket(eta, None, True, BASE, eta, BASE) == 'RISK'
    assert _bucket(eta, None, False, BASE, eta,
        eta + timedelta(seconds=1)) == 'RISK'


def test_source_cannot_be_counted_twice():
    eta = BASE + timedelta(days=1)
    source = OpenSourceDTO('shipment', '42', 1, 2, 'C', eta, None, False)
    with pytest.raises(ValueError, match='重複'):
        OpenOrdersDTO(1, 1, BASE, eta, BASE, (source, source))


def test_eta_requires_timezone():
    with pytest.raises(DomainError) as caught:
        _time('2026-10-09T13:00:00')
    assert caught.value.code == 'INVALID_INPUT'
