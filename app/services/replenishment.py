"""B03 immutable runs and v1 RunProvider. The caller owns its transaction."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import copy

from flask import current_app
from app.contracts import (OpenOrdersDTO, OpenSourceDTO, RunDTO, RunItemDTO, WarningDTO,
                           dto_dict, quantity, require_utc)
from app.extensions import db
from app.models import (Store, User, Product, StoreProduct, PolicyVersion, DeliveryCycle,
                        SalesDaily, Inventory, ReplenishmentRun, RunItem)
from app.providers import get_provider
from app.services.clock import aware, utc_naive, round_window, TAIPEI
from app.services.errors import DomainError
from app.services.inventory import _lock_store, _authorize, _business_now, _audit
from app.services.forecasting import MODEL_VERSION, calculate, decimal_value, risks, text

ID_MAX = 2_147_483_647


def authorize(session, store_id, actor_id, *, lock=False):
    quantity(store_id, minimum=1, maximum=ID_MAX)
    quantity(actor_id, minimum=1, maximum=ID_MAX)
    store = session.get(Store, store_id)
    if not store or not store.active:
        raise DomainError('NOT_FOUND', '門市不存在或不可存取', 404)
    actor = _authorize(session, actor_id, store)
    if actor.role not in ('manager', 'admin'):
        raise DomainError('FORBIDDEN', '僅店長／管理員可核對計算', 403)
    return _lock_store(session, store_id) if lock else store


def _cycle(session, store_id, cycle_id, baseline):
    quantity(cycle_id, minimum=1, maximum=ID_MAX)
    cycle = session.execute(db.select(DeliveryCycle).where(DeliveryCycle.id == cycle_id)
        .execution_options(populate_existing=True).with_for_update(read=True)).scalar_one_or_none()
    if not cycle or cycle.store_id != store_id or cycle.cancelled:
        raise DomainError('INVALID_CYCLE', '配送輪次不存在或不可用', 422)
    arrival = aware(cycle.arrival_at)
    delta = arrival - baseline
    if (aware(cycle.baseline_at) != baseline or aware(cycle.cutoff_at) != baseline + timedelta(hours=1)
            or delta.days < 1 or delta.seconds or delta.microseconds):
        raise DomainError('INVALID_CYCLE', '請選本輪每日21:00的有效到貨輪次', 422)
    return cycle, delta.days, baseline + timedelta(days=1 + delta.days)


def _window(now, baseline=None):
    b, cutoff = round_window(now)
    if not b <= now < cutoff or (baseline is not None and baseline != b):
        raise DomainError('CUTOFF_PASSED', '僅本輪21:00–22:00可產生或重新試算；歷史快照仍可讀取', 409)
    return b


def _json(value):
    return current_app.json.loads(current_app.json.dumps(value))


def _sources(session, store, baseline, end, now, product_ids):
    try:
        value = get_provider('open_orders').get_open_orders(store_id=store.id, baseline_at=baseline,
            protection_end=end, evaluated_at=now, session=session)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DomainError('PROVIDER_MISMATCH', '未結提供者回應不符合合約v1', 409) from exc
    if not isinstance(value, OpenOrdersDTO):
        raise DomainError('PROVIDER_MISMATCH', '未結提供者未回傳合約v1', 409)
    # Revalidate even a mutated/faulty producer DTO; never double count a source.
    try:
        value.__post_init__()
        quantity(value.store_id, minimum=1, maximum=ID_MAX)
        quantity(value.store_version, minimum=1, maximum=ID_MAX)
        for source in value.sources:
            quantity(source.product_id, minimum=1, maximum=ID_MAX)
            if type(source.disputed) is not bool:
                raise ValueError('invalid dispute flag')
            source.__post_init__()
            if source.source_type not in ('pending', 'committed', 'shipment', 'replacement'):
                raise ValueError('unknown source type')
            if (source.bucket == 'U' and source.source_type != 'pending') or (
                    source.bucket == 'C' and source.source_type == 'pending'):
                raise ValueError('invalid source bucket')
            if not isinstance(source.source_id, str) or not source.source_id:
                raise ValueError('missing source identity')
    except (ValueError, TypeError, AttributeError, DomainError) as exc:
        raise DomainError('PROVIDER_MISMATCH', '未結來源重複或不符合扣抵合約', 409) from exc
    if ((value.store_id, value.store_version, value.baseline_at, value.protection_end, value.evaluated_at)
            != (store.id, store.calculation_version, baseline, end, now)
            or any(s.product_id not in product_ids for s in value.sources)):
        raise DomainError('PROVIDER_MISMATCH', '未結來源門市／版本／時間／商品不一致', 409)
    return tuple(sorted(value.sources, key=lambda s: (s.product_id, s.source_type, s.source_id)))


def _warning(value):
    return WarningDTO(value['code'], value['message'], copy.deepcopy(value['details']), value['version'])


def _source(value):
    return OpenSourceDTO(value['source_type'], value['source_id'], value['product_id'], value['quantity'],
        value['bucket'], datetime.fromisoformat(value['eta']),
        datetime.fromisoformat(value['deduction_expires_at']) if value['deduction_expires_at'] else None,
        value['disputed'])


def _item(row):
    data = copy.deepcopy(row.output_snapshot)
    return RunItemDTO(product_id=row.product_id, mode=row.mode, h=data['h'],
        mu=Decimal(data['mu']) if data['mu'] is not None else None,
        target_stock=Decimal(data['target_stock']) if data['target_stock'] is not None else None,
        raw_qty=Decimal(data['raw_qty']) if data['raw_qty'] is not None else None,
        suggested_qty=row.suggested_qty, pack_size=data['pack_size'], lead_days=data['lead_days'],
        safety_stock=data['safety_stock'], capacity=data['capacity'], policy_version=data['policy_version'],
        inventory_version=data['inventory_version'], sources=tuple(_source(v) for v in data['sources']),
        warnings=tuple(_warning(v) for v in row.warnings), input_snapshot=copy.deepcopy(row.input_snapshot),
        timeline_committed=tuple(data['timeline_committed']), timeline_with_pending=tuple(data['timeline_with_pending']),
        manual_forecast=None, run_item_id=row.id)


def _run(row, items):
    return RunDTO(row.id, row.store_id, row.cycle_id, row.store_version, aware(row.baseline_at),
        aware(row.actual_generated_at), aware(row.data_through_at), aware(row.risk_evaluated_at),
        datetime.fromisoformat(row.snapshot['protection_end']), row.model_version, tuple(items), row.warning_version)


def _model(item, *, baseline, end, arrival, lead, now, sources, final=None):
    warnings = [w for w in item.warnings if w.code in ('FORECAST_INSUFFICIENT', 'INVENTORY_GAP', 'NEGATIVE_BOOK')]
    if item.h is None or not item.input_snapshot['forecast_quality']['valid']:
        if any(s.bucket == 'RISK' for s in sources):
            warnings.append(WarningDTO('LOGISTICS_RISK', '未結來源含期外、逾期或爭議；未扣抵需求', {}))
        if any(s.bucket == 'U' for s in sources):
            warnings.append(WarningDTO('PENDING_SUPPLY', '待接單仍未成為承諾', {}))
        return replace(item, lead_days=lead, sources=sources, warnings=tuple(warnings))
    total = item.input_snapshot['sales_total']
    mu, target, raw, suggested = calculate(total, lead_days=lead, safety_stock=item.safety_stock,
                                          h=item.h, sources=sources, pack_size=item.pack_size)
    if suggested > 1_000_000:
        return replace(item, mode='unavailable', mu=None, target_stock=None, raw_qty=None,
            suggested_qty=None, lead_days=lead, sources=sources, timeline_committed=(), timeline_with_pending=(),
            warnings=tuple(warnings + [WarningDTO('INVALID_QUANTITY', '計算量超過技術上限；未截斷為可訂量', {
                'calculated_qty': suggested, 'maximum': 1_000_000})]))
    final = suggested if final is None else quantity(final)
    calculated, committed, pending = risks(mu=mu, target=target, raw=raw, suggested=suggested, final=final,
        pack=item.pack_size, capacity=item.capacity, policy=item.input_snapshot['policy_parameters'],
        sources=sources, baseline=baseline, end=end, arrival=arrival, h=item.h, evaluated_at=now)
    return replace(item, mu=decimal_value(mu), target_stock=decimal_value(target), raw_qty=decimal_value(raw),
        suggested_qty=suggested, lead_days=lead, sources=sources, warnings=tuple(warnings) + calculated,
        timeline_committed=committed, timeline_with_pending=pending)


class ReplenishmentService:
    def generate(self, *, store_id, actor_id, cycle_id, expected_version, session):
        store = authorize(session, store_id, actor_id, lock=True)
        quantity(expected_version, minimum=1, maximum=ID_MAX)
        if store.calculation_version != expected_version:
            raise DomainError('VERSION_CONFLICT', '門市資料已更新，請重新核對再計算', 409,
                              {'current_version': store.calculation_version})
        now = _business_now(session)
        baseline = _window(now)
        cycle, lead, end = _cycle(session, store.id, cycle_id, baseline)
        configured = session.execute(db.select(StoreProduct, Product, PolicyVersion)
            .join(Product, Product.id == StoreProduct.product_id)
            .join(PolicyVersion, PolicyVersion.id == StoreProduct.policy_version_id)
            .where(StoreProduct.store_id == store.id, StoreProduct.active.is_(True), Product.active.is_(True))
            .order_by(Product.id).execution_options(populate_existing=True).with_for_update(read=True)).all()
        if not configured:
            raise DomainError('NO_PRODUCTS', '本店未設定有效商品', 422)
        ids = {product.id for sp, product, policy in configured}
        # Inventory locks in product order precede sales/source locks.
        integrity = {pid: get_provider('integrity').get_integrity(store_id=store.id, product_id=pid,
                        baseline_at=baseline, session=session) for pid in sorted(ids)}
        sources = _sources(session, store, baseline, end, now, ids)
        items = []
        latest = []
        for sp, product, policy in configured:
            params = copy.deepcopy(policy.parameters)
            required = ('absolute_large_qty', 'deviation_floor', 'deviation_multiplier')
            if (policy.store_id != store.id or policy.product_id != product.id or aware(policy.effective_at) > baseline
                    or params.get('review_days') != 1 or params.get('model_version') != MODEL_VERSION
                    or params.get('warning_version') != '1'
                    or any(type(params.get(k)) is not int or params[k] < 1 for k in required)
                    or any(params.get(k) != v for k, v in (
                        ('safety_stock', sp.safety_stock), ('capacity', sp.capacity), ('pack_size', product.pack_size),
                        ('lead_days', sp.lead_days)))):
                raise DomainError('INVALID_POLICY', '政策版本／參數不一致，請先核對設定', 409)
            state = integrity[product.id]
            if (state.store_id, state.product_id, state.store_version) != (store.id, product.id, store.calculation_version):
                raise DomainError('PROVIDER_MISMATCH', '庫存提供者門市／商品／版本不一致', 409)
            sales = session.execute(db.select(SalesDaily).where(SalesDaily.store_id == store.id,
                SalesDaily.product_id == product.id,
                SalesDaily.business_date.between((baseline - timedelta(days=6)).astimezone(TAIPEI).date(),
                    baseline.astimezone(TAIPEI).date()))
                .order_by(SalesDaily.business_date).execution_options(populate_existing=True)
                .with_for_update(read=True)).scalars().all()
            by_day = {row.business_date: row for row in sales}
            window, invalid, total = [], [], 0
            for days in range(6, -1, -1):
                at = baseline - timedelta(days=days)
                day = at.astimezone(TAIPEI).date()
                row = by_day.get(day)
                reason = ('missing' if row is None else 'invalid_interval' if
                    row.interval_start != utc_naive(at - timedelta(days=1)) or row.interval_end != utc_naive(at)
                    else 'not_open' if row.is_open is not True else 'stockout' if row.was_stockout is not False
                    else 'invalid_quantity' if type(row.sold_qty) is not int or not 0 <= row.sold_qty <= 1_000_000
                    else None)
                if reason:
                    invalid.append(dict(date=day.isoformat(), reason=reason))
                if row is not None:
                    if row.interval_end <= utc_naive(baseline) and reason != 'invalid_interval':
                        latest.append(aware(row.interval_end))
                    total += row.sold_qty
                window.append(dict(date=day.isoformat(), sold_qty=row.sold_qty if row else None,
                    is_open=row.is_open if row else None, was_stockout=row.was_stockout if row else None,
                    interval_start=aware(row.interval_start).isoformat() if row else None,
                    interval_end=aware(row.interval_end).isoformat() if row else None,
                    batch_id=row.batch_id if row else None, import_mode=row.import_mode if row else None,
                    applied_at=aware(row.applied_at).isoformat() if row and row.applied_at else None,
                    movement_id=row.movement_id if row else None))
            warnings = list(state.warnings)
            if not state.usable and not any(w.code in ('INVENTORY_GAP', 'NEGATIVE_BOOK') for w in warnings):
                warnings.append(WarningDTO('INVENTORY_GAP', '缺少有效盤點或連續日常入帳，H不可用', {}))
            if invalid:
                warnings.append(WarningDTO('FORECAST_INSUFFICIENT', '預測資料不足／需求可能被低估；不以零補齊', {
                    'invalid_days': invalid}))
            snapshot = dict(sku=product.sku, product_name=product.name, sales=window, sales_total=total,
                forecast_quality=dict(valid=not invalid, invalid_days=invalid), integrity=_json(dto_dict(state)),
                policy_version_id=policy.id, policy_version=policy.version, policy_parameters=params,
                manual_forecast=None, source_provider=dict(name=type(get_provider('open_orders')).__name__,
                    test_only=current_app.extensions['service_providers']['open_orders'][1]))
            usable = state.usable and not invalid
            item = RunItemDTO(product.id, 'model' if usable else 'unavailable', state.h,
                Decimal(0) if usable else None, Decimal(0) if usable else None, Decimal(0) if usable else None,
                0 if usable else None, product.pack_size, lead, sp.safety_stock, sp.capacity, policy.version,
                state.inventory_version, (), tuple(warnings), snapshot, (), ())
            items.append(_model(item, baseline=baseline, end=end, arrival=aware(cycle.arrival_at), lead=lead,
                                now=now, sources=tuple(s for s in sources if s.product_id == product.id)))
        row = ReplenishmentRun(store_id=store.id, cycle_id=cycle.id, actor_id=actor_id,
            store_version=store.calculation_version, baseline_at=utc_naive(baseline), actual_generated_at=utc_naive(now),
            data_through_at=utc_naive(max(latest) if latest else baseline - timedelta(days=7)),
            risk_evaluated_at=utc_naive(now), model_version=MODEL_VERSION, warning_version='1', calculation_mode='model',
            snapshot=dict(protection_end=end.isoformat(), cycle_arrival_at=aware(cycle.arrival_at).isoformat(),
                formula='R=1; P=1+L; S=mu*P+SS; raw=max(0,S-H-U-C); Q=ceil(raw/pack)*pack',
                decimal_precision=60))
        session.add(row)
        session.flush()
        persisted = []
        for item in items:
            data = _json(dto_dict(item))
            data['formula'] = row.snapshot['formula']
            record = RunItem(run_id=row.id, product_id=item.product_id, mode=item.mode, mu=item.mu,
                target_stock=item.target_stock, raw_qty=item.raw_qty, suggested_qty=item.suggested_qty,
                input_snapshot=data.pop('input_snapshot'), warnings=data.pop('warnings'), output_snapshot=data)
            session.add(record)
            persisted.append(record)
        _audit(session, actor_id, store.id, 'replenishment.generated', f'run:{row.id}', {},
               {'run_id': row.id, 'store_version': store.calculation_version}, now)
        session.flush()
        return _run(row, [_item(record) for record in persisted])

    def get_run(self, *, run_id, store_id, actor_id, session):
        authorize(session, store_id, actor_id)
        quantity(run_id, minimum=1, maximum=ID_MAX)
        row = session.get(ReplenishmentRun, run_id)
        if not row or row.store_id != store_id:
            raise DomainError('NOT_FOUND', '計算快照不存在或不可存取', 404)
        if row.model_version != MODEL_VERSION:
            raise DomainError('PROVIDER_MISMATCH', '此快照不是正式B計算結果', 409)
        rows = session.execute(db.select(RunItem).where(RunItem.run_id == row.id)
            .order_by(RunItem.product_id)).scalars().all()
        return _run(row, [_item(record) for record in rows])

    def evaluate(self, *, run_id, store_id, actor_id, cycle_id, final_quantities,
                 manual_confirmations, evaluated_at, session):
        store = authorize(session, store_id, actor_id, lock=True)
        require_utc(evaluated_at)
        run = self.get_run(run_id=run_id, store_id=store_id, actor_id=actor_id, session=session)
        if run.store_version != store.calculation_version:
            raise DomainError('VERSION_CONFLICT', '計算輸入已更新，請建立新快照', 409,
                              {'current_version': store.calculation_version})
        _window(evaluated_at, run.baseline_at)
        # Explicit current evaluation time is owned by the trusted calling service.
        _window(_business_now(session), run.baseline_at)
        cycle, lead, end = _cycle(session, store_id, cycle_id, run.baseline_at)
        if not isinstance(final_quantities, dict) or any(type(k) is not int for k in final_quantities):
            raise DomainError('INVALID_INPUT', '最終量須以商品id對應整數件數', 400)
        ids = {i.product_id for i in run.items}
        if set(final_quantities) - ids:
            raise DomainError('INVALID_INPUT', '最終量含快照外商品', 400)
        for value in final_quantities.values():
            quantity(value)
        if manual_confirmations:
            raise DomainError('UNSUPPORTED_MODE', 'B03尚未提供人工預測；請勿傳入人工確認', 422)
        sources = _sources(session, store, run.baseline_at, end, evaluated_at, ids)
        items = tuple(_model(item, baseline=run.baseline_at, end=end, arrival=aware(cycle.arrival_at),
            lead=lead, now=evaluated_at, sources=tuple(s for s in sources if s.product_id == item.product_id),
            final=final_quantities.get(item.product_id)) for item in run.items)
        return replace(run, cycle_id=cycle.id, protection_end=end, risk_evaluated_at=evaluated_at, items=items)
