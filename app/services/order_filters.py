"""Shared, validated order list filters in Taipei business dates."""
from datetime import date, datetime, time, timedelta
from flask import request
from app.models import Order
from app.services.clock import TAIPEI, utc_naive
from app.services.errors import DomainError

STATUSES = ('SUBMITTED', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'CHANGE_PENDING',
    'PARTIALLY_SHIPPED', 'SHIPPED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CLOSED_WITH_VARIANCE')


def filtered(query):
    for name in ('number', 'status', 'from_date', 'to_date'):
        if len(request.args.getlist(name)) > 1:
            raise DomainError('INVALID_INPUT', '搜尋條件不可重複', 400)
    number = request.args.get('number', '').strip()
    if len(number) > 64:
        raise DomainError('INVALID_INPUT', '單號最多64字', 400)
    if number:
        query = query.where(Order.number.contains(number, autoescape=True))
    status = request.args.get('status')
    if status:
        if status not in STATUSES:
            raise DomainError('INVALID_INPUT', '訂單狀態無效', 400)
        query = query.where(Order.status == status)
    dates = {}
    for key in ('from_date', 'to_date'):
        if request.args.get(key):
            try:
                dates[key] = date.fromisoformat(request.args[key])
            except ValueError:
                raise DomainError('INVALID_INPUT', '請輸入有效日期', 400)
    if len(dates) == 2 and dates['from_date'] > dates['to_date']:
        raise DomainError('INVALID_INPUT', '起日不得晚於迄日', 400)
    try:
        if 'from_date' in dates:
            query = query.where(Order.submitted_at >= utc_naive(datetime.combine(dates['from_date'], time(), TAIPEI)))
        if 'to_date' in dates:
            query = query.where(Order.submitted_at < utc_naive(datetime.combine(dates['to_date'] + timedelta(days=1), time(), TAIPEI)))
    except OverflowError:
        raise DomainError('INVALID_INPUT', '日期超出可查詢範圍，請修正日期', 400)
    return query
