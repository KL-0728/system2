"""D-owned operational task projection and completion."""
from datetime import timedelta
from sqlalchemy import event, select
from uuid import uuid4

from app.extensions import db
from app.models import (OperationalTask, Order, OrderItem, PolicyVersion,
    Shipment, ShipmentItem, ReceiptItem, ReceiptVariance, SupplyChangeRequest,
    FulfillmentEvent, User, Store)
from app.services.clock import aware, business_now, utc_naive
from app.services.errors import DomainError
from app.services.version import bump_store


def _lock_store(session, store_id):
    store = session.execute(db.select(Store).where(Store.id == store_id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
    if store is None or not store.active:
        raise DomainError('NOT_FOUND', '門市不存在', 404)
    return store


@event.listens_for(OrderItem, 'after_insert')
def _initial_response_task(mapper, connection, item):
    """Create the headquarters response deadline in C's order transaction."""
    order = connection.execute(select(Order.__table__).where(
        Order.id == item.order_id)).mappings().one()
    if order['fixture_only']:
        return
    policy = connection.execute(select(PolicyVersion.__table__).where(
        PolicyVersion.store_id == order['store_id'],
        PolicyVersion.product_id == item.product_id).order_by(
        PolicyVersion.version.desc()).limit(1)).mappings().one()
    response_minutes = int(policy['parameters'].get('supply_response_minutes', 60))
    connection.execute(OperationalTask.__table__.insert().values(
        store_id=order['store_id'], owner_role='operator',
        source_type='order_item', source_id=str(item.id),
        task_type='respond_order', policy_version_id=policy['id'],
        due_at=order['submitted_at'] + timedelta(minutes=response_minutes),
        created_at=order['submitted_at'], version=1))


def policy_setting(session, store_id, product_id, name, default):
    row = session.execute(db.select(PolicyVersion).where(
        PolicyVersion.store_id == store_id,
        PolicyVersion.product_id == product_id).order_by(
        PolicyVersion.version.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        raise DomainError('POLICY_MISSING', '門市商品政策不存在', 409)
    value = row.parameters.get(name, default)
    if type(value) is not int or value <= 0:
        raise DomainError('POLICY_INVALID', '期限政策設定無效', 409)
    return value


def list_tasks(session, store_id, role, *, order_id=None, include_completed=False):
    query = db.select(OperationalTask).where(OperationalTask.store_id == store_id)
    if not include_completed:
        query = query.where(OperationalTask.completed_at.is_(None))
    if role != 'admin':
        query = query.where(OperationalTask.owner_role == role)
    rows = session.execute(query.order_by(OperationalTask.due_at,
        OperationalTask.id)).scalars().all()
    if order_id is not None:
        item_ids = set(session.execute(db.select(OrderItem.id).where(
            OrderItem.order_id == order_id)).scalars())
        shipment_ids = set(session.execute(db.select(Shipment.id).where(
            Shipment.order_id == order_id)).scalars())
        shipment_item_ids = set(session.execute(db.select(ShipmentItem.id).where(
            ShipmentItem.shipment_id.in_(shipment_ids))).scalars()) if shipment_ids else set()
        change_ids = set(session.execute(db.select(SupplyChangeRequest.id).where(
            SupplyChangeRequest.order_item_id.in_(item_ids))).scalars()) if item_ids else set()
        variance_ids = set(session.execute(db.select(ReceiptVariance.id).join(ReceiptItem,
            ReceiptItem.id == ReceiptVariance.receipt_item_id).where(
            ReceiptItem.shipment_item_id.in_(shipment_item_ids))).scalars()) if shipment_item_ids else set()
        extra_ids = set(session.execute(db.select(FulfillmentEvent.id).where(
            FulfillmentEvent.order_item_id.in_(item_ids),
            FulfillmentEvent.event_type == 'EXTRA_HELD')).scalars()) if item_ids else set()
        allowed = {'order_item': item_ids, 'shipment_item': shipment_item_ids,
            'change': change_ids, 'variance': variance_ids,
            'extra_event': extra_ids}
        rows = [r for r in rows if r.source_type in allowed and
            r.source_id.isdigit() and int(r.source_id) in allowed[r.source_type]]
    now = business_now()
    return [dict(id=r.id, type=r.task_type, source=f'{r.source_type}:{r.source_id}',
        task_type=r.task_type, source_type=r.source_type,
        source_id=r.source_id, due_at=aware(r.due_at).isoformat(),
        overdue=r.completed_at is None and aware(r.due_at) < now,
        completed_at=aware(r.completed_at).isoformat() if r.completed_at else None,
        result=r.result, details=r.result) for r in rows]


def complete_task(session, store_id, source_type, source_id, task_type,
                  actor_id, result=None):
    row = session.execute(db.select(OperationalTask).where(
        OperationalTask.store_id == store_id,
        OperationalTask.source_type == source_type,
        OperationalTask.source_id == source_id,
        OperationalTask.task_type == task_type).with_for_update()).scalar_one_or_none()
    if row and row.completed_at is None:
        row.completed_at = utc_naive(business_now())
        row.completed_by = actor_id
        row.result = result or {'action': 'completed'}
        row.version += 1
    return row


def create_task(session, store_id, role, source_type, source_id, task_type,
                due_at, product_id=None):
    row = session.execute(db.select(OperationalTask).where(
        OperationalTask.store_id == store_id,
        OperationalTask.source_type == source_type,
        OperationalTask.source_id == source_id,
        OperationalTask.task_type == task_type).with_for_update()).scalar_one_or_none()
    if row:
        return row
    policy_query = db.select(PolicyVersion).where(PolicyVersion.store_id == store_id)
    if product_id is not None:
        policy_query = policy_query.where(PolicyVersion.product_id == product_id)
    policy = session.execute(policy_query.order_by(
        PolicyVersion.version.desc(), PolicyVersion.id.desc())).scalars().first()
    if policy is None:
        raise ValueError('門市政策版本不存在')
    row = OperationalTask(store_id=store_id, owner_role=role,
        source_type=source_type, source_id=source_id, task_type=task_type,
        policy_version_id=policy.id, due_at=utc_naive(due_at),
        created_at=utc_naive(business_now()))
    session.add(row)
    return row


def request_contact(session, store_id, actor_id, reason):
    actor = session.get(User, actor_id)
    if not actor or not actor.active or actor.role != 'manager' or \
            not any(s.id == store_id for s in actor.stores):
        raise DomainError('FORBIDDEN', '僅本店店長可建立聯絡待辦', 403)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise DomainError('INVALID_INPUT', '聯絡原因必填且不得超過500字', 400)
    store = _lock_store(session, store_id)
    policy = session.execute(db.select(PolicyVersion).where(
        PolicyVersion.store_id == store_id).order_by(
        PolicyVersion.version.desc())).scalars().first()
    minutes = int(policy.parameters.get('contact_minutes', 60)) if policy else 60
    task = create_task(session, store_id, 'manager', 'contact', uuid4().hex,
        'contact_headquarters', business_now() + timedelta(minutes=minutes))
    task.result = {'reason': reason.strip()}
    bump_store(store)
    return task


def resolve_contact(session, task_id, actor_id, result):
    actor = session.get(User, actor_id)
    task = session.get(OperationalTask, task_id)
    if not actor or not actor.active or actor.role != 'manager' or not task or \
            not any(s.id == task.store_id for s in actor.stores):
        raise DomainError('NOT_FOUND', '聯絡待辦不存在', 404)
    if not isinstance(result, str) or not result.strip() or len(result) > 500:
        raise DomainError('INVALID_INPUT', '處理結果必填且不得超過500字', 400)
    store = _lock_store(session, task.store_id)
    task = session.execute(db.select(OperationalTask).where(
        OperationalTask.id == task_id).execution_options(
        populate_existing=True).with_for_update()).scalar_one()
    if task.task_type != 'contact_headquarters' or task.completed_at:
        raise DomainError('INVALID_STATE', '待辦已處理或類型不符', 409)
    task.completed_at = utc_naive(business_now())
    task.completed_by = actor_id
    task.result = {**(task.result or {}), 'outcome': result.strip()}
    task.version += 1
    bump_store(store)
    return task
