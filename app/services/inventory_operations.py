"""B05 damaged stock and reconciliation workflows. Caller owns the transaction."""
from app.contracts import InventoryMutation, quantity, require_utc
from app.extensions import db
from app.models import InventoryMovement, InventoryReconciliation, CountSubmissionKey
from app.services.errors import DomainError
from app.services.inventory import (InventoryService, _lock_store, _authorize, _inventory,
                                   _text, _version, _audit, _business_now)

class InventoryOperations:
    def remove_damaged(self, *, store_id, product_id, actor_id, kind, qty,
                       expected_version, source_id, occurred_at, reason, session):
        for value in (store_id, product_id, actor_id):
            quantity(value, minimum=1, maximum=2_147_483_647)
        store = _lock_store(session, store_id)
        _authorize(session, actor_id, store, count=True)
        row = _inventory(session, store_id, product_id, lock=True)
        if kind not in ('disposal', 'return'):
            raise DomainError('INVALID_INPUT', '只受理損壞品報廢或實物退回', 400)
        quantity(qty, minimum=1)
        _text(source_id, '異動來源', 100)
        _text(reason, '異動理由', 500)
        _version(expected_version)
        try:
            require_utc(occurred_at)
        except (ValueError, TypeError):
            raise DomainError('INVALID_TIME','異動時間須為 aware UTC',400)
        mutation = InventoryMutation(store_id, product_id, kind, source_id, -qty, -qty,
                                     expected_version, actor_id, occurred_at, reason)
        existing = session.execute(db.select(InventoryMovement.id).where(
            InventoryMovement.store_id==store_id, InventoryMovement.product_id==product_id,
            InventoryMovement.source_type==kind, InventoryMovement.source_id==source_id)
            .with_for_update()).first()
        # Successful retries precede new-version, availability and time checks.
        if existing:
            return InventoryService().apply_movement(mutation=mutation, session=session)
        if row.version != expected_version:
            raise DomainError('VERSION_CONFLICT', '庫存已更新，請核對數量後再登記', 409,
                              {'current_version':row.version})
        if qty > row.book_unsellable_qty or qty > row.book_physical_qty:
            raise DomainError('INSUFFICIENT_DAMAGED_STOCK', '移出數量超過目前實體或不可販售量', 422,
                              {'physical_book':row.book_physical_qty,'unsellable_book':row.book_unsellable_qty})
        return InventoryService().apply_movement(mutation=mutation, session=session)

    def resolve_with_count(self, *, task_id, expected_task_version, session, **count):
        quantity(task_id, minimum=1, maximum=2_147_483_647)
        _version(expected_task_version)
        for value in (count['store_id'],count['product_id'],count['actor_id']):
            quantity(value,minimum=1,maximum=2_147_483_647)
        store = _lock_store(session, count['store_id'])
        _authorize(session, count['actor_id'], store, count=True)
        _inventory(session, store.id, count['product_id'], lock=True)
        task = session.execute(db.select(InventoryReconciliation).where(
            InventoryReconciliation.id==task_id, InventoryReconciliation.store_id==store.id,
            InventoryReconciliation.product_id==count['product_id'])
            .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
        if task is None:
            raise DomainError('NOT_FOUND', '對帳案件不存在或不可存取', 404)
        _text(count['request_key'], '盤點請求鍵', 100)
        key = session.execute(db.select(CountSubmissionKey).where(
            CountSubmissionKey.store_id==store.id, CountSubmissionKey.user_id==count['actor_id'],
            CountSubmissionKey.request_key==count['request_key']).with_for_update()).scalar_one_or_none()
        if key:
            if task.resolved_by!=count['actor_id'] or (task.resolution or {}).get('request_key')!=count['request_key']:
                raise DomainError('IDEMPOTENCY_CONFLICT', '此請求鍵屬於另一筆盤點處理', 409)
            # Also compare the reconciliation resource version in the original request.
            if (task.resolution or {}).get('expected_task_version')!=expected_task_version:
                raise DomainError('IDEMPOTENCY_CONFLICT', '同一對帳請求內容不同', 409)
            return InventoryService().submit_count(session=session, **count)
        if task.status!='OPEN':
            raise DomainError('ALREADY_RESOLVED', '案件已處理，請讀取原處理紀錄', 409)
        if task.version!=expected_task_version:
            raise DomainError('VERSION_CONFLICT', '對帳案件版本已更新', 409,
                              {'current_task_version':task.version})
        if task.source_type not in ('negative_book','sales_covered'):
            raise DomainError('UNSUPPORTED_RECONCILIATION', '此案件須依原業務來源處理', 409)
        old = dict(status=task.status,version=task.version,resolution=task.resolution)
        result = InventoryService().submit_count(session=session, **count)
        if task.status!='RESOLVED':
            raise DomainError('RECONCILIATION_NOT_RESOLVED', '有效盤點尚未涵蓋此案件，整筆處理未保存', 409)
        task.resolution = {**(task.resolution or {}), 'method':'count',
            'request_key':count['request_key'], 'expected_task_version':expected_task_version,
            'count_id':result.count_id, 'revision_id':result.revision_id,
            'count_version':result.revision, 'reason':count['reason']}
        _audit(session,count['actor_id'],store.id,'inventory.reconciliation_resolved',
            f'inventory-reconciliation:{task.id}',old,
            dict(status=task.status,version=task.version,resolution=task.resolution),_business_now(session))
        session.flush()
        return result
