from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from flask import current_app
from app.extensions import db
from app.contracts import (WarningDTO, OpenSourceDTO, OpenOrdersDTO, IntegrityDTO, RunItemDTO,
    RunDTO, MovementResult, FulfillmentSummaryDTO, OrderDTO)
from app.models import Store, Product, Inventory, InventoryMovement, DeliveryCycle, Order, OrderItem, ReplenishmentRun, RunItem
from app.services.clock import business_now, aware, utc_naive
from app.services.errors import DomainError
from app.testing.factories import require_fixture_mode


class ControlledOpenOrders:
    def __init__(self, scenario='normal'):
        self.scenario = scenario

    def get_open_orders(self, *, store_id, baseline_at, protection_end, evaluated_at, session):
        require_fixture_mode()
        store = session.get(Store, store_id)
        product = session.execute(db.select(Product).order_by(Product.id)).scalars().first()
        sources = ()
        if self.scenario in ('pending', 'committed', 'late', 'disputed', 'expired'):
            bucket = {'pending': 'U', 'committed': 'C'}.get(self.scenario, 'RISK')
            sources = (OpenSourceDTO('pending' if self.scenario in ('pending','expired') else 'committed',
                'controlled-1', product.id, 12, bucket,
                protection_end + timedelta(days=1) if self.scenario == 'late' else baseline_at + timedelta(days=1),
                evaluated_at - timedelta(seconds=1) if self.scenario == 'expired' else baseline_at + timedelta(minutes=60),
                self.scenario == 'disputed'),)
        return OpenOrdersDTO(store_id, store.calculation_version, baseline_at, protection_end, evaluated_at, sources)


class ControlledIntegrity:
    def __init__(self, scenario='normal'):
        self.scenario = scenario

    def get_integrity(self, *, store_id, product_id, baseline_at, session):
        require_fixture_mode()
        store = session.get(Store, store_id)
        warnings, missing, physical = (), (), 20
        if self.scenario == 'gap':
            missing = ((baseline_at - timedelta(days=1)).date().isoformat(),)
            warnings = (WarningDTO('INVENTORY_GAP', '日常銷售尚未連續入帳', {'dates': missing}),)
        if self.scenario == 'negative':
            physical = -1
            warnings = (WarningDTO('NEGATIVE_BOOK', '帳面負值，請先對帳', {}),)
        return IntegrityDTO(store_id, product_id, 1, store.calculation_version, physical, 0,
            None if self.scenario == 'no_count' else baseline_at, missing, warnings)


class ControlledRuns:
    def __init__(self, scenario='normal'):
        self.scenario = scenario

    def get_run(self, *, run_id, store_id, actor_id, session):
        require_fixture_mode()
        store = session.get(Store, store_id)
        cycle = session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id == store_id)
            .order_by(DeliveryCycle.id)).scalars().first()
        now = business_now()
        b = aware(cycle.baseline_at)
        end = b + timedelta(days=2)
        products = session.execute(db.select(Product).order_by(Product.id)).scalars().all()
        persisted = session.get(ReplenishmentRun, run_id)
        persisted_items = {}
        if persisted and persisted.store_id == store_id and persisted.model_version == 'controlled-test-v1':
            persisted_items = {i.product_id: i.id for i in session.execute(
                db.select(RunItem).where(RunItem.run_id == run_id)).scalars()}
        items = []
        for product in products:
            mode = {'direct': 'direct', 'insufficient': 'unavailable', 'manual': 'manual'}.get(self.scenario, 'model')
            warnings = ()
            if mode in ('direct', 'unavailable'):
                warnings = (WarningDTO('DIRECT_ORDER' if mode == 'direct' else 'FORECAST_INSUFFICIENT',
                    '無法計算有效模型建議', {'missing_days': ['2026-10-07']}),)
            elif mode == 'manual':
                warnings = (WarningDTO('MANUAL_FORECAST', '每輪須確認人工預測', {}),)
            timeline = () if mode in ('direct', 'unavailable') else ({'at': cycle.arrival_at,
                'ending_stock': '30', 'stockout_qty': '0', 'capacity_exceeded': False},)
            items.append(RunItemDTO(product.id, mode, 20, None if mode in ('direct','unavailable') else Decimal('20'),
                None if mode in ('direct','unavailable') else Decimal('50'),
                None if mode in ('direct','unavailable') else Decimal('30'),
                None if mode in ('direct','unavailable') else 30, product.pack_size, 1, 10, 100, 1, 1,
                (), warnings, {'fixture_only': True, 'sales': [20]*7, 'data_source': 'controlled-runs'},
                timeline, timeline, {'daily_demand': '20', 'valid_until': end, 'reason': '合成的人工預測測試案例',
                    'actor_id': actor_id, 'created_at': b} if mode == 'manual' else None,
                persisted_items.get(product.id)))
        return RunDTO(run_id, store_id, cycle.id, store.calculation_version, b, now, b, now, end,
            'controlled-test-v1', tuple(items))

    def evaluate(self, *, run_id, store_id, actor_id, cycle_id, final_quantities,
            manual_confirmations, evaluated_at, session):
        run = self.get_run(run_id=run_id, store_id=store_id, actor_id=actor_id, session=session)
        cycle = session.get(DeliveryCycle, cycle_id)
        if not cycle or cycle.store_id != store_id or cycle.cancelled:
            raise DomainError('INVALID_CYCLE', '配送輪次不可用')
        if cycle.id != run.cycle_id:
            raise DomainError('FIXTURE_SCENARIO_UNSUPPORTED', '此替身固定 L1，其他輪次請另注入受控案例')
        changed = []
        for item in run.items:
            from app.contracts import quantity
            final = quantity(final_quantities.get(item.product_id, item.suggested_qty or 0))
            warnings = list(item.warnings)
            if final and final % item.pack_size:
                warnings.append(WarningDTO('INVALID_PACK', '請選有效整箱量', {}))
            if final >= 100:
                warnings.append(WarningDTO('LARGE_QUANTITY', '大量需求須具體確認', {'final_qty': final}))
            if self.scenario == 'time_risk' and evaluated_at >= run.baseline_at + timedelta(minutes=30):
                warnings.append(WarningDTO('LOGISTICS_RISK', '測試 ETA 已逾期', {'scenario': 'time_risk'}))
            changed.append(replace(item, warnings=tuple(warnings)))
        return replace(run, risk_evaluated_at=evaluated_at, items=tuple(changed))


class ControlledInventoryWriter:
    """Deliberately a test double: records same-transaction writes and can fail after flush."""
    def __init__(self, fail_after_write=False):
        self.fail_after_write = fail_after_write

    def apply_movement(self, *, mutation, session):
        require_fixture_mode()
        row = session.execute(db.select(Inventory).where(Inventory.store_id == mutation.store_id,
            Inventory.product_id == mutation.product_id).with_for_update()).scalar_one()
        existing = session.execute(db.select(InventoryMovement).where(
            InventoryMovement.store_id == mutation.store_id, InventoryMovement.product_id == mutation.product_id,
            InventoryMovement.source_type == mutation.source_type, InventoryMovement.source_id == mutation.source_id)).scalar_one_or_none()
        store = session.get(Store, mutation.store_id)
        if existing:
            if (existing.physical_delta, existing.unsellable_delta, existing.reason, existing.actor_id,
                    existing.occurred_at) != (mutation.physical_delta, mutation.unsellable_delta,
                    mutation.reason, mutation.actor_id, utc_naive(mutation.occurred_at)):
                raise DomainError('IDEMPOTENCY_CONFLICT', '同一庫存來源內容不同', 409)
            return MovementResult(existing.id, existing.resulting_version, store.calculation_version,
                row.book_physical_qty, row.book_unsellable_qty, True)
        if row.version != mutation.expected_version:
            raise DomainError('VERSION_CONFLICT', '庫存版本衝突', 409)
        row.book_physical_qty += mutation.physical_delta
        row.book_unsellable_qty += mutation.unsellable_delta
        row.version += 1
        store.calculation_version += 1
        movement = InventoryMovement(store_id=mutation.store_id, product_id=mutation.product_id,
            physical_delta=mutation.physical_delta, unsellable_delta=mutation.unsellable_delta,
            source_type=mutation.source_type, source_id=mutation.source_id, reason=mutation.reason,
            actor_id=mutation.actor_id, occurred_at=utc_naive(mutation.occurred_at),
            applied_at=utc_naive(business_now()), resulting_version=row.version)
        session.add(movement)
        session.flush()
        if self.fail_after_write:
            raise DomainError('CONTROLLED_FAILURE', '寫入後受控失敗，供 D 測試同交易回滾', 422)
        return MovementResult(movement.id, row.version, store.calculation_version,
            row.book_physical_qty, row.book_unsellable_qty, False)


class ControlledFulfillment:
    def get_summary(self, *, order_id, store_id, actor_id, session):
        require_fixture_mode()
        return FulfillmentSummaryDTO(order_id, store_id, 1,
            ({'source': 'controlled-fulfillment', 'status': 'SUBMITTED', 'committed_qty': 0},), (), ())


class FixtureOrders:
    def get_order(self, *, order_id, store_id, actor_id, session):
        require_fixture_mode()
        row = session.get(Order, order_id)
        if not row or row.store_id != store_id or not row.fixture_only:
            raise DomainError('NOT_FOUND', '測試訂單不存在', 404)
        items = session.execute(db.select(OrderItem).where(OrderItem.order_id == row.id)).scalars().all()
        return OrderDTO(row.id, row.store_id, row.cycle_id, row.version, aware(row.submitted_at),
            tuple({'id': i.id, 'product_id': i.product_id, 'original_qty': i.original_qty,
                'product_snapshot': i.product_snapshot} for i in items), {'fixture_only': True})


def install_test_providers(module):
    require_fixture_mode()
    from app.providers import register_provider
    providers = {
        'B': {'open_orders': ControlledOpenOrders()},
        'C': {'runs': ControlledRuns(), 'integrity': ControlledIntegrity(),
            'open_orders': ControlledOpenOrders(), 'fulfillment': ControlledFulfillment()},
        'D': {'inventory_writer': ControlledInventoryWriter(), 'orders': FixtureOrders()},
    }
    for name, provider in providers[module].items():
        if name not in current_app.extensions['service_providers']:
            register_provider(name, provider, test_only=True)
