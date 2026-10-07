from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import current_app
from app.extensions import db
from app.models.audit import BusinessClock
from app.services.errors import DomainError

TAIPEI = ZoneInfo('Asia/Taipei')


def server_now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utc_naive(value):
    if value.tzinfo is None:
        raise ValueError('時間輸入必須含時區')
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def business_now():
    if current_app.config['APP_ENV'] == 'production':
        return server_now()
    clock = db.session.get(BusinessClock, 1)
    if clock is None:
        raise DomainError('CLOCK_NOT_INITIALIZED', '請先建立獨立示範資料', 503)
    anchor = aware(clock.business_anchor)
    return anchor if clock.paused else anchor + (server_now() - aware(clock.server_anchor))


def set_clock(actor, target, paused=True):
    if current_app.config['APP_ENV'] == 'production' or actor.role != 'admin' or not actor.active:
        raise DomainError('FORBIDDEN', '無權設定業務時鐘', 403)
    utc_naive(target)
    row = db.session.execute(db.select(BusinessClock).where(BusinessClock.id == 1).with_for_update()).scalar_one()
    current = aware(row.business_anchor)
    if not row.paused:
        current += server_now() - aware(row.server_anchor)
    if aware(target) < current:
        raise DomainError('CLOCK_BACKWARDS', '時鐘不得倒退；案例起點須透過安全重設', 409)
    row.business_anchor, row.server_anchor, row.paused = utc_naive(target), utc_naive(server_now()), paused
    from app.services.audit import record_event
    record_event(actor.id, None, 'clock.set', 'clock:1', {'time': current.isoformat()}, {'time': target.isoformat()})


def round_window(now):
    local = aware(now).astimezone(TAIPEI)
    baseline = local.replace(hour=21, minute=0, second=0, microsecond=0)
    return baseline.astimezone(timezone.utc), (baseline + timedelta(hours=1)).astimezone(timezone.utc)
