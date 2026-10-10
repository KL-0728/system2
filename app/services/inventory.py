"""B01 inventory accounting. Callers own the session and commit/rollback.

All writers serialize on Store before Inventory and source keys. Movement/count revision
records remain immutable; neither receipt nor count overwrites book quantities.
"""
from dataclasses import asdict, dataclass
from datetime import timedelta
from hashlib import sha256
import json
from uuid import uuid4

from flask import current_app, g, has_request_context

from app.contracts import IntegrityDTO, InventoryMutation, MovementResult, WarningDTO, quantity, require_utc
from app.extensions import db
from app.models import (AuditEvent, BusinessClock, CountSubmissionKey, Inventory, InventoryCount,
    InventoryCountRevision, InventoryMovement, InventoryReconciliation, SalesDaily, Store, User)
from app.services.clock import TAIPEI, aware, round_window, server_now, utc_naive
from app.services.errors import DomainError
from app.services.version import bump_store

SALES_SOURCES = ('sales', 'sales_correction')


def _business_now(session):
    # The common clock's rules, read through the caller's transaction/session.
    if current_app.config['APP_ENV'] == 'production':
        return server_now()
    clock = session.execute(db.select(BusinessClock).where(BusinessClock.id == 1)
        .execution_options(populate_existing=True).with_for_update(read=True)).scalar_one_or_none()
    if clock is None:
        raise DomainError('CLOCK_NOT_INITIALIZED', '請先建立獨立示範資料', 503)
    anchor = aware(clock.business_anchor)
    return anchor if clock.paused else anchor + (server_now() - aware(clock.server_anchor))


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DomainError('INVALID_INPUT', f'{name}必填且不得超過{maximum}字元', 400)
    return value


def _version(value):
    return quantity(value, minimum=1, maximum=2_147_483_647)


def _hash(payload):
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _lock_store(session, store_id):
    row = session.execute(db.select(Store).where(Store.id == store_id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
    if not row or not row.active:
        raise DomainError('NOT_FOUND', '門市不存在或不可存取', 404)
    return row


def _inventory(session, store_id, product_id, *, lock=False):
    query = db.select(Inventory).where(Inventory.store_id == store_id, Inventory.product_id == product_id)
    if lock:
        query = query.execution_options(populate_existing=True).with_for_update()
    row = session.execute(query).scalar_one_or_none()
    if row is None:
        raise DomainError('NOT_FOUND', '門市商品庫存不存在', 404)
    return row


def _authorize(session, actor_id, store, *, count=False):
    # Reads/writes receive the authenticated actor from their outer business entry.
    actor = session.get(User, actor_id)
    roles = ('manager',) if count else ('manager', 'operator', 'admin')
    if not actor or not actor.active or actor.role not in roles:
        raise DomainError('FORBIDDEN', '無此操作權限', 403)
    if actor.role == 'manager' and store not in actor.stores:
        raise DomainError('NOT_FOUND', '門市不存在或不可存取', 404)
    return actor


def _audit(session, actor_id, store_id, action, entity, old, new, now):
    # Use the caller's session, including independent MySQL sessions in D.
    event = AuditEvent(actor_id=actor_id, store_id=store_id, action=action, entity=entity,
        old=old, new=new, server_time=utc_naive(server_now()), business_time=utc_naive(now),
        request_id=getattr(g, 'request_id', str(uuid4())) if has_request_context() else str(uuid4()))
    session.add(event)


def _snapshot(session, entity, action):
    event = session.execute(db.select(AuditEvent).where(AuditEvent.entity == entity,
        AuditEvent.action == action).with_for_update()).scalar_one_or_none()
    if event is None:
        # A legacy/test-double movement has no authoritative B result to replay.
        raise DomainError('SOURCE_RESULT_UNAVAILABLE', '此來源缺少正式入帳快照，請先核對', 409)
    return event.new


def _posted_day(session, store_id, product_id, cutoff, *, lock=False):
    query = db.select(SalesDaily).where(SalesDaily.store_id == store_id,
        SalesDaily.product_id == product_id, SalesDaily.business_date == cutoff.astimezone(TAIPEI).date())
    if lock:
        query = query.execution_options(populate_existing=True).with_for_update()
    row = session.execute(query).scalar_one_or_none()
    if row is None or row.import_mode != 'daily_posting' or row.applied_at is None or row.movement_id is None:
        return False
    query = db.select(InventoryMovement).where(InventoryMovement.id == row.movement_id)
    if lock:
        query = query.with_for_update()
    movement = session.execute(query).scalar_one_or_none()
    return (row.interval_end == utc_naive(cutoff)
        and row.interval_start == utc_naive(cutoff - timedelta(days=1))
        and movement is not None and movement.store_id == store_id and movement.product_id == product_id
        and movement.source_type in SALES_SOURCES and movement.occurred_at == utc_naive(cutoff))


@dataclass(frozen=True)
class CountResult:
    count_id: int
    revision_id: int
    revision: int
    physical_delta: int
    unsellable_delta: int
    movement: MovementResult
    replayed: bool = False


class InventoryService:
    def apply_movement(self, *, mutation, session):
        if not isinstance(mutation, InventoryMutation):
            raise DomainError('INVALID_INPUT', '須使用合約v1的InventoryMutation', 400)
        _text(mutation.source_type, '來源類別', 40)
        _text(mutation.source_id, '來源識別', 100)
        _text(mutation.reason, '異動理由', 500)
        _version(mutation.expected_version)
        for identity in (mutation.store_id, mutation.product_id, mutation.actor_id):
            quantity(identity, minimum=1, maximum=2_147_483_647)
        store = _lock_store(session, mutation.store_id)
        _authorize(session, mutation.actor_id, store)
        row = _inventory(session, store.id, mutation.product_id, lock=True)
        payload = asdict(mutation)
        payload['occurred_at'] = mutation.occurred_at.isoformat()
        payload_hash = _hash(payload)
        existing = session.execute(db.select(InventoryMovement).where(
            InventoryMovement.store_id == store.id, InventoryMovement.product_id == mutation.product_id,
            InventoryMovement.source_type == mutation.source_type, InventoryMovement.source_id == mutation.source_id)
            .with_for_update()).scalar_one_or_none()
        if existing:
            saved = _snapshot(session, f'inventory-movement:{existing.id}', 'inventory.apply')
            if saved['payload_hash'] != payload_hash:
                raise DomainError('IDEMPOTENCY_CONFLICT', '同一庫存來源內容不同', 409)
            return MovementResult(**saved['result'], replayed=True)
        now = _business_now(session)
        if mutation.occurred_at > now:
            raise DomainError('INVALID_TIME', '庫存異動時間不得晚於業務時間')
        if row.version != mutation.expected_version:
            raise DomainError('VERSION_CONFLICT', '庫存版本衝突，請重新核對', 409,
                {'current_version': row.version})
        physical = row.book_physical_qty + mutation.physical_delta
        unsellable = row.book_unsellable_qty + mutation.unsellable_delta
        if not -2_147_483_648 <= physical <= 2_147_483_647 or not 0 <= unsellable <= 2_147_483_647:
            raise DomainError('INVALID_QUANTITY', '帳面數量超出儲存範圍或不可販售量為負')
        if mutation.source_type in SALES_SOURCES and mutation.unsellable_delta != 0:
            raise DomainError('INVALID_QUANTITY', '銷售不得扣減不可販售量')
        if (physical < unsellable and mutation.source_type not in (*SALES_SOURCES, 'count_revision')
                and mutation.physical_delta - mutation.unsellable_delta < 0):
            raise DomainError('INVALID_QUANTITY', '非銷售異動不得造成或擴大負可售帳面')
        old = {'physical_book': row.book_physical_qty, 'unsellable_book': row.book_unsellable_qty,
            'inventory_version': row.version, 'store_version': store.calculation_version}
        row.book_physical_qty, row.book_unsellable_qty = physical, unsellable
        row.version += 1
        bump_store(store)
        row.updated_at = utc_naive(now)
        row.reconciliation_required = (physical < unsellable or (row.reconciliation_required
            and mutation.source_type not in ('sales_correction', 'count_revision')))
        movement = InventoryMovement(store_id=store.id, product_id=mutation.product_id,
            physical_delta=mutation.physical_delta, unsellable_delta=mutation.unsellable_delta,
            source_type=mutation.source_type, source_id=mutation.source_id, reason=mutation.reason,
            actor_id=mutation.actor_id, occurred_at=utc_naive(mutation.occurred_at),
            applied_at=utc_naive(now), resulting_version=row.version)
        session.add(movement)
        session.flush()
        if row.reconciliation_required:
            session.add(InventoryReconciliation(store_id=store.id, product_id=row.product_id,
                source_type='negative_book', source_id=f'movement:{movement.id}',
                reason='帳面可售量為負，須有效盤點或更正', status='OPEN', created_at=utc_naive(now)))
        else:
            pending = session.execute(db.select(InventoryReconciliation).where(
                InventoryReconciliation.store_id == store.id, InventoryReconciliation.product_id == row.product_id,
                InventoryReconciliation.source_type == 'negative_book', InventoryReconciliation.status == 'OPEN')
                .with_for_update()).scalars()
            for task in pending:
                task.status, task.resolved_at, task.resolved_by = 'RESOLVED', utc_naive(now), mutation.actor_id
                task.version += 1
                task.resolution = {'movement_id': movement.id, 'reason': mutation.reason}
        result = MovementResult(movement.id, row.version, store.calculation_version, physical, unsellable, False)
        saved_result = asdict(result)
        saved_result.pop('replayed')
        _audit(session, mutation.actor_id, store.id, 'inventory.apply', f'inventory-movement:{movement.id}',
            old, {'payload_hash': payload_hash, 'result': saved_result}, now)
        session.flush()
        return result

    def get_integrity(self, *, store_id, product_id, baseline_at, session):
        require_utc(baseline_at)
        b, _ = round_window(baseline_at)
        if baseline_at != b:
            raise DomainError('INVALID_TIME', '庫存基準須為21:00')
        store = _lock_store(session, store_id)
        row = _inventory(session, store_id, product_id, lock=True)
        counted = aware(row.counted_at)
        valid_baseline = counted if counted <= baseline_at and round_window(counted)[0] == counted else None
        missing = []
        if valid_baseline:
            day = valid_baseline + timedelta(days=1)
            while day <= baseline_at:
                if not _posted_day(session, store_id, product_id, day, lock=True):
                    missing.append(day.astimezone(TAIPEI).date().isoformat())
                day += timedelta(days=1)
        warnings = []
        if valid_baseline is None or missing:
            warnings.append(WarningDTO('INVENTORY_GAP', '缺少有效盤點基準或日常銷售未連續入帳',
                {'dates': missing, 'baseline_missing': valid_baseline is None}))
        if row.reconciliation_required or row.book_physical_qty < row.book_unsellable_qty or row.book_unsellable_qty < 0:
            warnings.append(WarningDTO('NEGATIVE_BOOK', '帳面可售量為負或非法，請先對帳',
                {'physical_book': row.book_physical_qty, 'unsellable_book': row.book_unsellable_qty,
                    'reconciliation_required': row.reconciliation_required}))
        return IntegrityDTO(store_id, product_id, row.version, store.calculation_version,
            row.book_physical_qty, row.book_unsellable_qty,
            None if row.reconciliation_required else valid_baseline, tuple(missing), tuple(warnings))

    def submit_count(self, *, store_id, product_id, actor_id, cutoff_at, physical_qty,
            unsellable_qty, expected_version, request_key, reason, session,
            correction=False, expected_count_version=None):
        require_utc(cutoff_at)
        quantity(physical_qty)
        quantity(unsellable_qty, maximum=physical_qty)
        _version(expected_version)
        _text(request_key, '盤點請求鍵', 100)
        _text(reason, '盤點理由', 500)
        if type(correction) is not bool:
            raise DomainError('INVALID_INPUT', 'correction須為布林值', 400)
        if correction:
            _version(expected_count_version)
        elif expected_count_version is not None:
            raise DomainError('INVALID_INPUT', '初次盤點不可指定修訂版本', 400)
        payload = dict(product_id=product_id, cutoff_at=cutoff_at.isoformat(), physical_qty=physical_qty,
            unsellable_qty=unsellable_qty, expected_version=expected_version, reason=reason,
            correction=correction, expected_count_version=expected_count_version)
        payload_hash = _hash(payload)
        store = _lock_store(session, store_id)
        _authorize(session, actor_id, store, count=True)
        row = _inventory(session, store_id, product_id, lock=True)
        key = session.execute(db.select(CountSubmissionKey).where(CountSubmissionKey.store_id == store_id,
            CountSubmissionKey.user_id == actor_id, CountSubmissionKey.request_key == request_key)
            .with_for_update()).scalar_one_or_none()
        if key:
            if key.payload_hash != payload_hash:
                raise DomainError('IDEMPOTENCY_CONFLICT', '同一盤點請求鍵內容不同', 409)
            saved = _snapshot(session, f'inventory-count-revision:{key.revision_id}', 'inventory.count')
            return CountResult(**{k: v for k, v in saved.items() if k != 'movement'},
                movement=MovementResult(**saved['movement'], replayed=True), replayed=True)
        now = _business_now(session)
        b, cutoff = round_window(now)
        if cutoff_at != b or not b <= now < cutoff:
            raise DomainError('INVALID_COUNT_WINDOW', '僅受理當日21:00實盤，須於21:00至22:00提交')
        if aware(row.counted_at) > cutoff_at:
            raise DomainError('VERSION_CONFLICT', '已有更新的盤點基準', 409)
        if row.version != expected_version:
            raise DomainError('VERSION_CONFLICT', '庫存版本衝突，請重新核對', 409,
                {'current_version': row.version})
        if not _posted_day(session, store_id, product_id, cutoff_at, lock=True):
            raise DomainError('INVENTORY_GAP', '本區間日常銷售須先入帳再提交盤點',
                details={'dates': [cutoff_at.astimezone(TAIPEI).date().isoformat()]})
        count = session.execute(db.select(InventoryCount).where(InventoryCount.store_id == store_id,
            InventoryCount.product_id == product_id, InventoryCount.cutoff_at == utc_naive(cutoff_at))
            .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
        if count:
            if not correction:
                raise DomainError('COUNT_ALREADY_EXISTS', '同截止點已有盤點；修正須明確指定修訂與理由', 409)
            if count.version != expected_count_version:
                raise DomainError('VERSION_CONFLICT', '盤點修訂版本衝突', 409,
                    {'current_count_version': count.version})
            previous = session.execute(db.select(InventoryCountRevision).where(
                InventoryCountRevision.count_id == count.id, InventoryCountRevision.revision == count.version)
                .with_for_update()).scalar_one()
            physical_delta = physical_qty - previous.physical_qty
            unsellable_delta = unsellable_qty - previous.unsellable_qty
            count.version += 1
        else:
            if correction:
                raise DomainError('NOT_FOUND', '找不到可修訂的盤點', 404)
            # Reverse only post-cutoff movements, not the submission-time book.
            later = session.execute(db.select(InventoryMovement).where(
                InventoryMovement.store_id == store_id, InventoryMovement.product_id == product_id,
                InventoryMovement.occurred_at > utc_naive(cutoff_at)).with_for_update()).scalars().all()
            baseline_physical = row.book_physical_qty - sum(m.physical_delta for m in later)
            baseline_unsellable = row.book_unsellable_qty - sum(m.unsellable_delta for m in later)
            count = InventoryCount(store_id=store_id, product_id=product_id, cutoff_at=utc_naive(cutoff_at),
                baseline_physical_qty=baseline_physical, baseline_unsellable_qty=baseline_unsellable, version=1)
            session.add(count)
            session.flush()
            physical_delta, unsellable_delta = physical_qty - baseline_physical, unsellable_qty - baseline_unsellable
        mutation = InventoryMutation(store_id, product_id, 'count_revision', f'count:{count.id}:revision:{count.version}',
            physical_delta, unsellable_delta, expected_version, actor_id, cutoff_at, reason)
        movement = self.apply_movement(mutation=mutation, session=session)
        row.physical_qty, row.unsellable_qty, row.counted_at = physical_qty, unsellable_qty, utc_naive(cutoff_at)
        revision = InventoryCountRevision(count_id=count.id, revision=count.version,
            physical_qty=physical_qty, unsellable_qty=unsellable_qty, physical_delta=physical_delta,
            unsellable_delta=unsellable_delta, expected_version=expected_version, reason=reason,
            actor_id=actor_id, submitted_at=utc_naive(now), movement_id=movement.movement_id)
        session.add(revision)
        session.flush()
        session.add(CountSubmissionKey(store_id=store_id, user_id=actor_id, request_key=request_key,
            payload_hash=payload_hash, revision_id=revision.id))
        result = CountResult(count.id, revision.id, count.version, physical_delta, unsellable_delta, movement)
        snapshot = asdict(result)
        snapshot.pop('replayed')
        snapshot['movement'].pop('replayed')
        _audit(session, actor_id, store_id, 'inventory.count', f'inventory-count-revision:{revision.id}',
            None, snapshot, now)
        session.flush()
        return result
