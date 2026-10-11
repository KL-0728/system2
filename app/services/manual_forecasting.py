"""B04 append-only manual values and historical information. Caller owns transaction."""
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.contracts import quantity
from app.extensions import db
from app.models import ManualForecastOverride, PolicyVersion, StoreProduct, Product, SalesDaily
from app.services.clock import aware, utc_naive, round_window, TAIPEI
from app.services.errors import DomainError
from app.services.inventory import _business_now, _audit
from app.services.version import bump_store

def demand(value):
    if not isinstance(value, (str, Decimal)) or isinstance(value, bool):
        raise DomainError('INVALID_FORECAST', '人工日需求須為非負Decimal字串，最多三位小數、上限1000000', 422)
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise DomainError('INVALID_FORECAST', '人工日需求格式不正確', 422)
    if (not number.is_finite() or number < 0 or number > 1_000_000
            or number.as_tuple().exponent < -3
            or (isinstance(value, str) and not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,3})?', value))):
        raise DomainError('INVALID_FORECAST', '人工日需求須為非負有限值，最多三位小數、上限1000000', 422)
    return number

def text_field(value, name, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DomainError('INVALID_INPUT', f'{name}必填且不得超過{maximum}字元', 400)
    return value.strip()

def day_value(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
        return date.fromisoformat(value)
    except ValueError:
        raise DomainError('INVALID_DATE', '日期須為YYYY-MM-DD', 400)

def configured_product(session, store_id, product_id):
    quantity(product_id, minimum=1, maximum=2_147_483_647)
    result = session.execute(db.select(StoreProduct, Product, PolicyVersion)
        .join(Product, Product.id == StoreProduct.product_id)
        .join(PolicyVersion, PolicyVersion.id == StoreProduct.policy_version_id)
        .where(StoreProduct.store_id == store_id, StoreProduct.product_id == product_id,
            StoreProduct.active.is_(True), Product.active.is_(True))
        .execution_options(populate_existing=True).with_for_update(read=True)).one_or_none()
    if result is None:
        raise DomainError('NOT_FOUND', '門市商品不存在或不可存取', 404)
    if result[2].store_id != store_id or result[2].product_id != product_id:
        raise DomainError('INVALID_POLICY', '商品政策不一致', 409)
    return result

def latest_reference(session, store_id, product_id, now):
    row = session.execute(db.select(ManualForecastOverride).where(
        ManualForecastOverride.store_id == store_id, ManualForecastOverride.product_id == product_id)
        .order_by(ManualForecastOverride.created_at.desc(), ManualForecastOverride.id.desc())
        .execution_options(populate_existing=True).with_for_update(read=True)).scalars().first()
    if row is None:
        return None
    return dict(override_id=row.id, daily_demand=format(row.daily_demand, 'f'), reason=row.reason,
        actor_id=row.actor_id, version=row.version, created_at=aware(row.created_at).isoformat(),
        valid_until=aware(row.valid_until).isoformat(), expired=aware(row.valid_until) <= now)

class ManualForecastService:
    def save(self, *, store_id, product_id, actor_id, daily_demand, reason, expected_version, session):
        from app.services.replenishment import authorize
        store = authorize(session, store_id, actor_id, lock=True)
        quantity(expected_version, minimum=1, maximum=2_147_483_647)
        if store.calculation_version != expected_version:
            raise DomainError('VERSION_CONFLICT', '資料已更新，請重新核對人工預測', 409,
                              {'current_version':store.calculation_version})
        value, reason = demand(daily_demand), text_field(reason, '人工預測理由')
        sp, product, policy = configured_product(session, store_id, product_id)
        now = _business_now(session)
        days = policy.parameters.get('manual_valid_days')
        if type(days) is not int or days < 1:
            raise DomainError('INVALID_POLICY', '人工預測期限政策無效', 409)
        try:
            expiry = round_window(now + timedelta(days=days))[0]
        except (OverflowError, ValueError):
            raise DomainError('INVALID_POLICY', '人工預測期限超過可表示範圍', 409)
        previous = latest_reference(session, store_id, product_id, now)
        row = ManualForecastOverride(store_id=store_id, product_id=product_id, daily_demand=value,
            reason=reason, actor_id=actor_id, created_at=utc_naive(now), valid_until=utc_naive(expiry),
            version=previous['version'] + 1 if previous else 1)
        session.add(row)
        bump_store(store)
        session.flush()
        result = latest_reference(session, store_id, product_id, now)
        _audit(session, actor_id, store_id, 'manual_forecast.saved', f'manual-forecast:{row.id}',
            {'previous_override_id':previous['override_id'] if previous else None},
            dict(reference=result, policy_version_id=policy.id, policy_version=policy.version,
                 valid_days=days, store_version=store.calculation_version), now)
        session.flush()
        return dict(manual_forecast=result, store_version=store.calculation_version)

    def annotate(self, *, store_id, product_id, actor_id, business_date, note,
                 expected_version, expected_sales_version, session):
        from app.services.replenishment import authorize
        store = authorize(session, store_id, actor_id, lock=True)
        quantity(expected_version, minimum=1, maximum=2_147_483_647)
        quantity(expected_sales_version, minimum=1, maximum=2_147_483_647)
        if store.calculation_version != expected_version:
            raise DomainError('VERSION_CONFLICT', '銷售或政策已更新，請重新核對註記', 409)
        configured_product(session, store_id, product_id)
        day = day_value(business_date)
        now = _business_now(session)
        if day > now.astimezone(TAIPEI).date():
            raise DomainError('INVALID_DATE', '未來銷售不能標為歷史資料', 422)
        if note is not None and (not isinstance(note, str) or len(note)>500):
            raise DomainError('INVALID_INPUT', '歷史註記最多500字元', 400)
        note = note.strip() or None if isinstance(note, str) else None
        row = session.execute(db.select(SalesDaily).where(SalesDaily.store_id==store_id,
            SalesDaily.product_id==product_id, SalesDaily.business_date==day)
            .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
        if row is None:
            raise DomainError('NOT_FOUND', '此日沒有銷售資料；註記不會補齊缺檔', 404)
        if row.version != expected_sales_version:
            raise DomainError('VERSION_CONFLICT', '銷售列已更新，請重新核對', 409)
        if row.event_note == note:
            return dict(sales_id=row.id, sales_version=row.version, store_version=store.calculation_version, unchanged=True)
        old = row.event_note
        row.event_note = note
        row.version += 1
        bump_store(store)
        _audit(session, actor_id, store_id, 'sales.historical_note', f'sales:{row.id}',
               {'event_note':old}, {'event_note':note, 'sales_version':row.version}, now)
        session.flush()
        return dict(sales_id=row.id, sales_version=row.version, store_version=store.calculation_version, unchanged=False)

    def options(self, *, store_id, actor_id, session):
        from app.services.replenishment import authorize
        authorize(session, store_id, actor_id, lock=True)
        now = _business_now(session)
        b = round_window(now)[0]
        rows = session.execute(db.select(StoreProduct, Product).join(Product, Product.id==StoreProduct.product_id)
            .where(StoreProduct.store_id==store_id, StoreProduct.active.is_(True), Product.active.is_(True))
            .order_by(Product.id)).all()
        result=[]
        for sp, product in rows:
            reference = latest_reference(session, store_id, product.id, now)
            sales = session.execute(db.select(SalesDaily).where(SalesDaily.store_id==store_id,
                SalesDaily.product_id==product.id, SalesDaily.business_date.between(
                    (b-timedelta(days=6)).astimezone(TAIPEI).date(),b.astimezone(TAIPEI).date()))
                .order_by(SalesDaily.business_date).execution_options(populate_existing=True)
                .with_for_update(read=True)).scalars().all()
            valid = len(sales)==7 and all(s.is_open is True and s.was_stockout is False
                and s.interval_end==utc_naive(round_window(aware(s.interval_end))[0])
                and s.interval_start==s.interval_end-timedelta(days=1)
                and aware(s.interval_end).astimezone(TAIPEI).date()==s.business_date
                and type(s.sold_qty) is int and 0<=s.sold_qty<=1_000_000 for s in sales)
            result.append(dict(product_id=product.id,sku=product.sku,name=product.name,pack_size=product.pack_size,
                forecast_valid=valid,latest_manual_forecast=reference,
                sales=[dict(date=s.business_date.isoformat(),sold_qty=s.sold_qty,event_note=s.event_note,
                            sales_version=s.version) for s in sales]))
        return result
