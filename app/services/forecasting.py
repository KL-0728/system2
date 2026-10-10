"""B03 deterministic daily model. Exact rational rounding avoids recurring-Decimal box errors."""
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

from app.contracts import WarningDTO, quantity

MODEL_VERSION = 'sma7-periodic-v1'


def decimal_value(value):
    with localcontext() as context:
        context.prec = 60
        return Decimal(value.numerator) / Decimal(value.denominator)


def text(value):
    return format(decimal_value(value), 'f')


def calculate(total, *, lead_days, safety_stock, h, sources, pack_size):
    mu = Fraction(total, 7)
    target = mu * (1 + lead_days) + safety_stock
    raw = max(Fraction(0), target - h - sum(s.quantity for s in sources if s.bucket in ('U', 'C')))
    # ceil numerator / denominator is exact, including exact box boundaries.
    boxes = (raw.numerator + raw.denominator * pack_size - 1) // (raw.denominator * pack_size)
    return mu, target, raw, boxes * pack_size


def timeline(*, baseline, end, arrival, mu, h, capacity, final_qty, sources, evaluated_at, pending):
    """Daily sales first, receipts second. Lost sales never become a backlog.

    RISK receipts with a future ETA are conditional previews only. Overdue receipts
    keep their original ETA in sources and are never silently added to today's H.
    """
    supply = [s for s in sources if s.eta >= evaluated_at and s.eta > baseline and
              (s.bucket == 'C' or (s.bucket == 'RISK' and s.source_type != 'pending' and not s.disputed)
               or (pending and s.bucket in ('U', 'RISK')))]
    horizon = max([end, arrival] + [s.eta for s in supply])
    receipts = {}
    for source in supply:
        receipts.setdefault(source.eta, []).append(dict(source_id=source.source_id,
            source_type=source.source_type, bucket=source.bucket, qty=source.quantity,
            conditional=source.bucket != 'C'))
    if final_qty:
        receipts.setdefault(arrival, []).append(dict(source_id='candidate', source_type='candidate',
            bucket='Q', qty=final_qty, conditional=True))
    points = set(receipts)
    day = baseline + timedelta(days=1)
    while day <= horizon:
        points.add(day)
        day += timedelta(days=1)
    points.add(horizon)
    stock = Fraction(h)
    result = [dict(at=baseline.isoformat(), demand='0', receipts=[], ending_stock=text(stock),
        stockout_qty='0', capacity_exceeded=False)]
    for at in sorted(points):
        demand = mu if at > baseline and (at - baseline).total_seconds() % 86400 == 0 else Fraction(0)
        lost = max(Fraction(0), demand - stock)
        stock = max(Fraction(0), stock - demand)
        incoming = sorted(receipts.get(at, []), key=lambda row: (row['source_type'], row['source_id']))
        stock += sum(row['qty'] for row in incoming)
        result.append(dict(at=at.isoformat(), demand=text(demand), receipts=incoming,
            ending_stock=text(stock), stockout_qty=text(lost),
            capacity_exceeded=bool(incoming) and stock > capacity))
    return tuple(result)


def risks(*, mu, target, raw, suggested, final, pack, capacity, policy, sources,
          baseline, end, arrival, h, evaluated_at):
    warnings = []
    if not mu:
        warnings.append(WarningDTO('ZERO_SALES', '近期無銷售，請確認安全庫存是否適當', {}))
    if Fraction(suggested) != raw:
        warnings.append(WarningDTO('PACK_ROUNDING', '建議量已向上取整箱', {'raw_qty': text(raw), 'pack_size': pack}))
    if any(s.bucket == 'U' for s in sources):
        warnings.append(WarningDTO('PENDING_SUPPLY', '待接單仍在期限內，扣抵不代表已承諾到貨', {}))
    if any(s.bucket == 'RISK' for s in sources):
        warnings.append(WarningDTO('LOGISTICS_RISK', '期外、逾期或爭議來源未扣抵需求；未來到貨仍可能重複', {
            'sources': [s.source_id for s in sources if s.bucket == 'RISK']}))
    if final % pack:
        warnings.append(WarningDTO('INVALID_PACK', '最終量須符合整箱，請自行選擇，不自動改量', {
            'lower': final - final % pack, 'upper': final + pack - final % pack, 'pack_size': pack}))
    if final >= policy['absolute_large_qty']:
        warnings.append(WarningDTO('LARGE_QUANTITY', '大量需求請核對件／箱與收貨安排', {'final_qty': final}))
    if ((suggested == 0 and final >= policy['deviation_floor']) or
            (suggested > 0 and final > max(policy['deviation_floor'], policy['deviation_multiplier'] * suggested))):
        warnings.append(WarningDTO('DEVIATION', '最終量明顯高於系統建議', {'final_qty': final, 'suggested_qty': suggested}))
    args = dict(baseline=baseline, end=end, arrival=arrival, mu=mu, h=h, capacity=capacity,
                final_qty=final, sources=sources, evaluated_at=evaluated_at)
    committed = timeline(**args, pending=False)
    with_pending = timeline(**args, pending=True)
    early = [row for row in committed if row['at'] <= arrival.isoformat() and Decimal(row['stockout_qty']) > 0]
    if early:
        warnings.append(WarningDTO('PRE_ARRIVAL_STOCKOUT', '新貨到達前可能缺貨；增加本次訂量無法消除此缺口', {
            'first_at': early[0]['at'], 'stockout_qty': text(sum(Fraction(r['stockout_qty']) for r in early))}))
    excess = [dict(curve=label, at=row['at'], ending_stock=row['ending_stock']) for label, curve in
        (('committed', committed), ('with_pending', with_pending)) for row in curve if row['capacity_exceeded']]
    if excess:
        warnings.append(WarningDTO('CAPACITY', '到貨後可能超出常規容量；保留輸入數量供確認', {
            'capacity': capacity, 'points': excess}))
    return tuple(warnings), committed, with_pending
