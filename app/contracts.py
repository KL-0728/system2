"""Frozen cross-module Python boundary, version 1. Providers never own commits."""
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from app.services.errors import DomainError

CONTRACT_VERSION = '1'
WARNING_VERSION = '1'
WARNING_LEVELS = {
    'PENDING_SUPPLY': 'info', 'ZERO_SALES': 'info', 'PACK_ROUNDING': 'info',
    'HISTORICAL_EVENT': 'info', 'LARGE_QUANTITY': 'important', 'DEVIATION': 'important',
    'CAPACITY': 'important', 'PRE_ARRIVAL_STOCKOUT': 'important',
    'LOGISTICS_RISK': 'important', 'MANUAL_FORECAST': 'important',
    'SPECIAL_DEMAND': 'important', 'DIRECT_ORDER': 'important',
    'FORECAST_INSUFFICIENT': 'block', 'INVENTORY_GAP': 'block',
    'NEGATIVE_BOOK': 'block', 'INVALID_QUANTITY': 'block', 'INVALID_PACK': 'block',
    'STALE_VERSION': 'block', 'CUTOFF_PASSED': 'block',
}


def quantity(value, minimum=0, maximum=1_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError('INVALID_QUANTITY', '數量須為範圍內的整數件數')
    return value


def require_utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError('DTO 時間必須為 aware UTC')


@dataclass(frozen=True)
class WarningDTO:
    code: str
    message: str
    details: dict
    version: str = WARNING_VERSION

    def __post_init__(self):
        if self.code not in WARNING_LEVELS or self.version != WARNING_VERSION:
            raise ValueError('未知警示代碼／版本')

    @property
    def level(self):
        return WARNING_LEVELS[self.code]


@dataclass(frozen=True)
class OpenSourceDTO:
    source_type: str  # pending / committed / shipment / replacement
    source_id: str    # globally unique within store + product + source_type
    product_id: int
    quantity: int
    bucket: str      # U / C / RISK; a source segment belongs to exactly one
    eta: datetime
    deduction_expires_at: datetime | None
    disputed: bool

    def __post_init__(self):
        quantity(self.quantity, minimum=1)
        require_utc(self.eta)
        if self.deduction_expires_at is not None:
            require_utc(self.deduction_expires_at)
        if self.bucket not in ('U', 'C', 'RISK') or (self.disputed and self.bucket != 'RISK'):
            raise ValueError('爭議來源不得有效扣抵')


@dataclass(frozen=True)
class OpenOrdersDTO:
    store_id: int
    store_version: int
    baseline_at: datetime
    protection_end: datetime
    evaluated_at: datetime
    sources: tuple[OpenSourceDTO, ...]

    def __post_init__(self):
        for time in (self.baseline_at, self.protection_end, self.evaluated_at):
            require_utc(time)
        seen = set()
        for source in self.sources:
            identity = (source.source_type, source.source_id, source.product_id)
            if identity in seen:
                raise ValueError('未結來源重複')
            seen.add(identity)
            if source.bucket in ('U', 'C'):
                if not self.baseline_at < source.eta <= self.protection_end or source.eta < self.evaluated_at:
                    raise ValueError('晚到／逾期來源不得有效扣抵')
                if source.bucket == 'U' and (source.deduction_expires_at is None
                        or source.deduction_expires_at <= self.evaluated_at):
                    raise ValueError('待接單扣抵期限已過')

    def totals(self, product_id):
        return {bucket: sum(s.quantity for s in self.sources if s.product_id == product_id and s.bucket == bucket)
            for bucket in ('U', 'C', 'RISK')}


@dataclass(frozen=True)
class IntegrityDTO:
    store_id: int
    product_id: int
    inventory_version: int
    store_version: int
    physical_book: int
    unsellable_book: int
    baseline_counted_at: datetime | None
    missing_dates: tuple[str, ...]
    warnings: tuple[WarningDTO, ...]

    @property
    def usable(self):
        return self.baseline_counted_at is not None and not self.missing_dates and self.physical_book >= self.unsellable_book >= 0

    @property
    def h(self):
        return self.physical_book - self.unsellable_book if self.usable else None


@dataclass(frozen=True)
class RunItemDTO:
    product_id: int
    mode: str  # model / manual / direct / unavailable
    h: int | None
    mu: Decimal | None
    target_stock: Decimal | None
    raw_qty: Decimal | None
    suggested_qty: int | None
    pack_size: int
    lead_days: int
    safety_stock: int
    capacity: int
    policy_version: int
    inventory_version: int
    sources: tuple[OpenSourceDTO, ...]
    warnings: tuple[WarningDTO, ...]
    input_snapshot: dict
    timeline_committed: tuple[dict, ...]
    timeline_with_pending: tuple[dict, ...]
    manual_forecast: dict | None = None
    run_item_id: int | None = None

    def __post_init__(self):
        if self.mode not in ('model', 'manual', 'direct', 'unavailable') or self.pack_size < 1 or self.lead_days < 1:
            raise ValueError('無效計算模式／政策')
        for value in (self.mu, self.target_stock, self.raw_qty):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value < 0):
                raise ValueError('模型量必須為非負有限 Decimal 或 null')
        if self.mode in ('direct', 'unavailable') and any(value is not None
                for value in (self.mu, self.target_stock, self.raw_qty, self.suggested_qty)):
            raise ValueError('無預測模式不得虛構模型量')
        if self.mode in ('model', 'manual') and any(value is None
                for value in (self.mu, self.target_stock, self.raw_qty, self.suggested_qty)):
            raise ValueError('有效模型模式必須有完整輸出')
        if self.suggested_qty is not None:
            quantity(self.suggested_qty)
            if self.suggested_qty % self.pack_size:
                raise ValueError('建議量須為整箱')
        if self.mode == 'direct' and (self.timeline_committed or self.timeline_with_pending):
            raise ValueError('特殊直接訂購不得虛構精確需求曲線')


@dataclass(frozen=True)
class RunDTO:
    run_id: int
    store_id: int
    cycle_id: int
    store_version: int
    baseline_at: datetime
    actual_generated_at: datetime
    data_through_at: datetime
    risk_evaluated_at: datetime
    protection_end: datetime
    model_version: str
    items: tuple[RunItemDTO, ...]
    warning_version: str = WARNING_VERSION

    def __post_init__(self):
        for value in (self.baseline_at, self.actual_generated_at, self.data_through_at,
                self.risk_evaluated_at, self.protection_end):
            require_utc(value)


@dataclass(frozen=True)
class InventoryMutation:
    store_id: int
    product_id: int
    source_type: str
    source_id: str
    physical_delta: int
    unsellable_delta: int
    expected_version: int
    actor_id: int
    occurred_at: datetime
    reason: str

    def __post_init__(self):
        quantity(self.physical_delta, -1_000_000)
        quantity(self.unsellable_delta, -1_000_000)
        require_utc(self.occurred_at)
        if not self.source_id or not self.reason:
            raise ValueError('庫存來源與理由必填')


@dataclass(frozen=True)
class MovementResult:
    movement_id: int
    inventory_version: int
    store_version: int
    physical_book: int
    unsellable_book: int
    replayed: bool


@dataclass(frozen=True)
class FulfillmentSummaryDTO:
    order_id: int
    store_id: int
    version: int
    items: tuple[dict, ...]
    timeline: tuple[dict, ...]
    tasks: tuple[dict, ...]


@dataclass(frozen=True)
class OrderDTO:
    order_id: int
    store_id: int
    cycle_id: int
    version: int
    submitted_at: datetime
    items: tuple[dict, ...]
    confirmation_snapshot: dict


class OpenOrdersProvider(Protocol):
    def get_open_orders(self, *, store_id: int, baseline_at: datetime, protection_end: datetime,
        evaluated_at: datetime, session) -> OpenOrdersDTO: ...


class RunProvider(Protocol):
    def get_run(self, *, run_id: int, store_id: int, actor_id: int, session) -> RunDTO: ...
    def evaluate(self, *, run_id: int, store_id: int, actor_id: int, cycle_id: int,
        final_quantities: dict[int, int], manual_confirmations: tuple[int, ...], evaluated_at: datetime, session) -> RunDTO: ...


class IntegrityProvider(Protocol):
    def get_integrity(self, *, store_id: int, product_id: int, baseline_at: datetime, session) -> IntegrityDTO: ...


class InventoryWriter(Protocol):
    def apply_movement(self, *, mutation: InventoryMutation, session) -> MovementResult: ...


class FulfillmentProvider(Protocol):
    def get_summary(self, *, order_id: int, store_id: int, actor_id: int, session) -> FulfillmentSummaryDTO: ...


class OrderProvider(Protocol):
    def get_order(self, *, order_id: int, store_id: int, actor_id: int, session) -> OrderDTO: ...


def dto_dict(value):
    result = asdict(value)
    def warnings(item):
        if isinstance(item, dict):
            if 'code' in item and item.get('version') == WARNING_VERSION and item['code'] in WARNING_LEVELS:
                item['level'] = WARNING_LEVELS[item['code']]
            for child in item.values():
                warnings(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                warnings(child)
    warnings(result)
    return result
