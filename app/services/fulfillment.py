"""D fulfillment operations. The outer HTTP entry owns commit and rollback."""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json
from uuid import uuid4
from flask import current_app, g, has_request_context

from app.contracts import FulfillmentSummaryDTO, InventoryMutation, quantity
from app.extensions import db
from app.models import (Order, OrderItem, Shipment, ShipmentItem, Receipt,
    ReceiptItem, ReceiptVariance, ReplacementAuthorization, SupplyChangeRequest,
    FulfillmentEvent, Inventory, User, DeliveryCycle, AuditEvent, Store, Product)
from app.providers import get_provider
from app.services.clock import aware, business_now, server_now, utc_naive
from app.services.errors import DomainError
from app.services.version import bump_store


def _hash(value):
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise DomainError('INVALID_INPUT', '內容不是有效 JSON', 400)
    return sha256(encoded).hexdigest()


def _text(value, label, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DomainError('INVALID_INPUT', f'{label}必填且不得超過{limit}字元', 400)
    return value.strip()


def _time(value, label='ETA'):
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return utc_naive(parsed)
    except (TypeError, ValueError):
        raise DomainError('INVALID_INPUT', f'{label}須含時區', 400)


def _lock_store(session, store_id):
    store = session.execute(db.select(Store).where(Store.id == store_id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
    if store is None or not store.active:
        raise DomainError('NOT_FOUND', '門市不存在', 404)
    return store


def _item(session, item_id, actor_id, roles, *, lock=True):
    actor = session.get(User, actor_id)
    if not actor or not actor.active or actor.role not in roles:
        raise DomainError('FORBIDDEN', '無此操作權限', 403)
    item = session.get(OrderItem, item_id)
    order = session.get(Order, item.order_id) if item else None
    if not order or (actor.role == 'manager' and
            not any(store.id == order.store_id for store in actor.stores)):
        raise DomainError('NOT_FOUND', '訂單品項不存在', 404)
    if order.fixture_only and current_app.config['APP_ENV'] != 'test' and \
            current_app.config['MODULE_DEV'] != 'D':
        raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
    if lock:
        _lock_store(session, order.store_id)
        order = session.execute(db.select(Order).where(Order.id == order.id)
            .execution_options(populate_existing=True).with_for_update()).scalar_one()
        item = session.execute(db.select(OrderItem).where(OrderItem.id == item_id)
            .execution_options(populate_existing=True).with_for_update()).scalar_one()
    return item, order


def _event(session, item, actor_id, kind, source, snapshot):
    session.add(FulfillmentEvent(order_item_id=item.id, actor_id=actor_id,
        source_key=source, event_type=kind, occurred_at=utc_naive(business_now()),
        snapshot=snapshot))


def _changed(session, item, order, actor_id, action, old, new):
    item.version += 1
    order.version += 1
    states = [row.status for row in session.execute(db.select(OrderItem).where(
        OrderItem.order_id == order.id).order_by(OrderItem.id)
        .execution_options(populate_existing=True).with_for_update()).scalars()]
    if len(set(states)) == 1:
        order.status = states[0]
    elif all(s in ('RECEIVED', 'CLOSED_WITH_VARIANCE', 'REJECTED', 'CANCELLED') for s in states):
        order.status = 'CLOSED_WITH_VARIANCE'
    elif any(s in ('PARTIALLY_RECEIVED', 'RECEIVED', 'CLOSED_WITH_VARIANCE') for s in states):
        order.status = 'PARTIALLY_RECEIVED'
    elif any(s in ('SHIPPED', 'PARTIALLY_SHIPPED') for s in states):
        order.status = 'PARTIALLY_SHIPPED'
    else:
        order.status = 'SUBMITTED'
    bump_store(_lock_store(session, order.store_id))
    session.add(AuditEvent(actor_id=actor_id, store_id=order.store_id,
        action=action, entity=f'order_item:{item.id}', old=old, new=new,
        server_time=utc_naive(server_now()),
        business_time=utc_naive(business_now()),
        request_id=getattr(g, 'request_id', str(uuid4()))
        if has_request_context() else str(uuid4())))


def _shipped(session, item_id, kind='original'):
    return sum(row.shipped_qty for row in session.execute(db.select(ShipmentItem).where(
        ShipmentItem.order_item_id == item_id, ShipmentItem.kind == kind)
        .execution_options(populate_existing=True).with_for_update()).scalars())


def _summary_item(session, item, requested_eta):
    lines = session.execute(db.select(ShipmentItem).where(
        ShipmentItem.order_item_id == item.id)).scalars().all()
    receipts = session.execute(db.select(ReceiptItem).join(ShipmentItem,
        ShipmentItem.id == ReceiptItem.shipment_item_id).where(
        ShipmentItem.order_item_id == item.id)).scalars().all()
    return dict(item_id=item.id, order_item_id=item.id,
        product_id=item.product_id, original_qty=item.original_qty,
        committed_qty=item.committed_qty, cancelled_qty=item.cancelled_qty,
        original_shipped_qty=sum(s.shipped_qty for s in lines if s.kind == 'original'),
        replacement_shipped_qty=sum(s.shipped_qty for s in lines if s.kind == 'replacement'),
        sellable_received_qty=sum(r.sellable_qty for r in receipts),
        damaged_received_qty=sum(r.damaged_qty for r in receipts),
        confirmed_short_qty=sum(r.short_qty for r in receipts),
        pending_receipt_qty=sum(s.shipped_qty - s.checked_qty for s in lines),
        disputed_qty=item.disputed_qty, status=item.status,
        eta=aware(item.eta).isoformat() if item.eta else None,
        requested_eta=aware(requested_eta).isoformat(),
        disputed=item.commitment_disputed, version=item.version)


class FulfillmentService:
    def get_summary(self, *, order_id, store_id, actor_id, session):
        actor = session.get(User, actor_id)
        order = session.get(Order, order_id)
        if not actor or not actor.active or actor.role not in ('manager', 'operator', 'admin'):
            raise DomainError('FORBIDDEN', '無此操作權限', 403)
        if not order or order.store_id != store_id or (actor.role == 'manager' and
                not any(s.id == store_id for s in actor.stores)):
            raise DomainError('NOT_FOUND', '訂單不存在', 404)
        if order.fixture_only and current_app.config['APP_ENV'] != 'test' and \
                current_app.config['MODULE_DEV'] != 'D':
            raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
        items = session.execute(db.select(OrderItem).where(OrderItem.order_id == order_id)
            .order_by(OrderItem.id)).scalars().all()
        cycle = session.get(DeliveryCycle, order.cycle_id)
        events = session.execute(db.select(FulfillmentEvent).where(
            FulfillmentEvent.order_item_id.in_([i.id for i in items]))
            .order_by(FulfillmentEvent.occurred_at, FulfillmentEvent.id)).scalars().all() if items else []
        from app.services.tasks import list_tasks
        return FulfillmentSummaryDTO(order_id, store_id, order.version,
            tuple(_summary_item(session, i, cycle.arrival_at) for i in items),
            tuple(dict(id=e.id, type=e.event_type, actor=e.actor_id, actor_id=e.actor_id,
                at=aware(e.occurred_at).isoformat(),
                occurred_at=aware(e.occurred_at).isoformat(),
                details=e.snapshot, snapshot=e.snapshot,
                source_key=e.source_key) for e in events),
            tuple(list_tasks(session, store_id, actor.role, order_id=order_id,
                include_completed=True)))

    def accept(self, *, item_id, actor_id, committed_qty, eta, session):
        quantity(committed_qty, 1)
        eta_value = _time(eta)
        item, order = _item(session, item_id, actor_id, ('operator', 'admin'))
        store = _lock_store(session, order.store_id)
        if item.status != 'SUBMITTED' or committed_qty != item.original_qty:
            raise DomainError('INVALID_STATE', '不同供貨條件須先提出變更', 409)
        cycle = session.get(DeliveryCycle, order.cycle_id)
        if cycle and eta_value > cycle.arrival_at:
            raise DomainError('CHANGE_REQUIRED', '晚於要求到貨日須先提出供貨變更', 409)
        if eta_value <= utc_naive(business_now()):
            raise DomainError('INVALID_ETA', 'ETA須晚於現在', 422)
        old = {'status': item.status}
        item.committed_qty, item.eta, item.status = committed_qty, eta_value, 'ACCEPTED'
        _event(session, item, actor_id, 'ACCEPTED', f'accept:{item.id}',
            {'committed_qty': committed_qty, 'eta': eta})
        _changed(session, item, order, actor_id, 'fulfillment.accept', old,
            {'status': item.status, 'committed_qty': committed_qty})
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'order_item', str(item.id), 'respond_order', actor_id)
        return item

    def reject(self, *, item_id, actor_id, reason, session):
        reason = _text(reason, '拒絕原因')
        item, order = _item(session, item_id, actor_id, ('operator', 'admin'))
        if item.status != 'SUBMITTED':
            raise DomainError('INVALID_STATE', '此品項不能拒絕', 409)
        item.status = 'REJECTED'
        _event(session, item, actor_id, 'REJECTED', f'reject:{item.id}', {'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.reject',
            {'status': 'SUBMITTED'}, {'status': 'REJECTED', 'reason': reason})
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'order_item', str(item.id), 'respond_order', actor_id)
        return item

    def cancel_pending(self, *, item_id, actor_id, reason, session):
        reason = _text(reason, '取消原因')
        item, order = _item(session, item_id, actor_id, ('manager', 'admin'))
        if item.status != 'SUBMITTED' or _shipped(session, item.id):
            raise DomainError('INVALID_STATE', '只能取消尚未接單且未出貨品項', 409)
        item.status = 'CANCELLED'
        item.cancelled_qty = item.original_qty
        _event(session, item, actor_id, 'CANCELLED', f'cancel:{item.id}', {'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.cancel_pending',
            {'status': 'SUBMITTED'}, {'status': 'CANCELLED', 'reason': reason})
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'order_item', str(item.id),
            'respond_order', actor_id, {'cancelled': True, 'reason': reason})
        return item

    def ship(self, *, order_id, actor_id, request_key, lines, session):
        key = _text(request_key, '請求識別', 100)
        if not isinstance(lines, list) or not lines:
            raise DomainError('INVALID_INPUT', '至少需要一筆出貨', 400)
        payload_hash = _hash(lines)
        order = session.get(Order, order_id)
        if not order:
            raise DomainError('NOT_FOUND', '訂單不存在', 404)
        if order.fixture_only and current_app.config['APP_ENV'] != 'test' and current_app.config['MODULE_DEV'] != 'D':
            raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
        actor = session.get(User, actor_id)
        if not actor or not actor.active or actor.role not in ('operator', 'admin'):
            raise DomainError('FORBIDDEN', '無此操作權限', 403)
        _lock_store(session, order.store_id)
        prior = session.execute(db.select(Shipment).where(Shipment.order_id == order_id,
            Shipment.request_key == key).execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
        if prior:
            if prior.payload_hash != payload_hash:
                raise DomainError('IDEMPOTENCY_CONFLICT', '相同識別的出貨內容不同', 409)
            return prior
        seen = set()
        prepared = []
        for line in lines:
            if not isinstance(line, dict):
                raise DomainError('INVALID_INPUT', '出貨品項格式錯誤', 400)
            item_id = line.get('item_id')
            kind = line.get('kind', 'original')
            auth_id = line.get('authorization_id')
            qty = quantity(line.get('quantity'), 1)
            if (item_id, kind) in seen or kind not in ('original', 'replacement'):
                raise DomainError('INVALID_INPUT', '同一批不可重複品項與類型', 400)
            seen.add((item_id, kind))
            item, found_order = _item(session, item_id, actor_id, ('operator', 'admin'))
            if found_order.id != order_id or item.commitment_disputed:
                raise DomainError('INVALID_STATE', '訂單不符或供貨仍有爭議', 409)
            eta = _time(line.get('eta'))
            if eta <= utc_naive(business_now()):
                raise DomainError('INVALID_ETA', 'ETA須晚於現在', 422)
            auth = None
            if kind == 'original':
                if auth_id is not None or item.status not in ('ACCEPTED', 'PARTIALLY_SHIPPED',
                        'PARTIALLY_RECEIVED', 'SHIPPED') or \
                        _shipped(session, item.id) + qty > item.committed_qty:
                    raise DomainError('INVALID_STATE', '出貨超過原承諾', 409)
            else:
                auth = session.execute(db.select(ReplacementAuthorization).where(
                    ReplacementAuthorization.id == auth_id).execution_options(
                    populate_existing=True).with_for_update()).scalar_one_or_none()
                variance = session.execute(db.select(ReceiptVariance).where(ReceiptVariance.id == auth.variance_id)
                    .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none() if auth else None
                receipt_item = session.get(ReceiptItem, variance.receipt_item_id) if variance else None
                original_line = session.get(ShipmentItem, receipt_item.shipment_item_id) if receipt_item else None
                if not auth or not original_line or original_line.order_item_id != item.id or \
                        auth.used_qty + auth.closed_qty + qty > auth.authorized_qty:
                    raise DomainError('INVALID_STATE', '補送未授權或額度不足', 409)
                auth.used_qty += qty
                auth.version += 1
            promised_eta = item.eta if kind == 'original' else auth.eta
            delayed = promised_eta is not None and eta > promised_eta
            delay_reason = _text(line.get('delay_reason'), '延遲原因') if delayed and line.get('delay_reason') else None
            if delayed and not delay_reason:
                raise DomainError('DELAY_REASON_REQUIRED', '物流預估晚於承諾，請填延遲原因；承諾變更須另走供貨提案', 422)
            prepared.append((item, kind, qty, eta, auth_id, delayed, delay_reason, promised_eta))
        shipment = Shipment(order_id=order_id, request_key=key, payload_hash=payload_hash,
            actor_id=actor_id, shipped_at=utc_naive(business_now()))
        session.add(shipment)
        session.flush()
        for item, kind, qty, eta, auth_id, delayed, delay_reason, promised_eta in prepared:
            line = ShipmentItem(shipment_id=shipment.id, order_item_id=item.id,
                kind=kind, authorization_id=auth_id, shipped_qty=qty, checked_qty=0,
                eta=eta, eta_disputed=delayed)
            session.add(line)
            session.flush()
            if kind == 'original':
                received = session.execute(db.select(ReceiptItem.id).join(ShipmentItem,
                    ShipmentItem.id == ReceiptItem.shipment_item_id).where(
                    ShipmentItem.order_item_id == item.id).limit(1)).first()
                item.status = 'PARTIALLY_RECEIVED' if received else (
                    'SHIPPED' if _shipped(session, item.id) >= item.committed_qty
                    else 'PARTIALLY_SHIPPED')
            _event(session, item, actor_id, 'SHIPPED', f'shipment_item:{line.id}',
                {'quantity': qty, 'kind': kind, 'eta': aware(eta).isoformat(),
                 'promised_eta': aware(promised_eta).isoformat() if promised_eta else None,
                 'delay_reason': delay_reason, 'delayed': delayed})
            _changed(session, item, order, actor_id, 'fulfillment.ship', {},
                {'shipment_id': shipment.id, 'quantity': qty, 'kind': kind})
            from app.services.tasks import create_task, policy_setting
            receipt_minutes = policy_setting(session, order.store_id, item.product_id,
                'receipt_minutes', 60)
            create_task(session, order.store_id, 'manager', 'shipment_item', str(line.id),
                'receive_shipment', aware(eta) + timedelta(minutes=receipt_minutes), item.product_id)
            if delayed:
                create_task(session, order.store_id, 'operator', 'shipment_item', str(line.id),
                    'investigate_shipment', business_now() + timedelta(minutes=60), item.product_id)
        return shipment

    def receive(self, *, shipment_id, actor_id, request_key, lines, session):
        key = _text(request_key, '請求識別', 100)
        if not isinstance(lines, list) or not lines:
            raise DomainError('INVALID_INPUT', '至少需要一筆核對品項', 400)
        shipment = session.get(Shipment, shipment_id)
        order = session.get(Order, shipment.order_id) if shipment else None
        if not order:
            raise DomainError('NOT_FOUND', '出貨批次不存在', 404)
        if order.fixture_only and current_app.config['APP_ENV'] != 'test' and current_app.config['MODULE_DEV'] != 'D':
            raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
        actor = session.get(User, actor_id)
        if not actor or not actor.active or actor.role not in ('manager', 'admin') or \
                (actor.role == 'manager' and not any(s.id == order.store_id for s in actor.stores)):
            raise DomainError('NOT_FOUND', '出貨批次不存在', 404)
        _lock_store(session, order.store_id)
        payload_hash = _hash(lines)
        previous = session.execute(db.select(Receipt).where(Receipt.store_id == order.store_id,
            Receipt.user_id == actor_id, Receipt.shipment_id == shipment_id,
            Receipt.request_key == key).execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
        if previous:
            if previous.payload_hash != payload_hash:
                raise DomainError('IDEMPOTENCY_CONFLICT', '相同識別的收貨內容不同', 409)
            return previous
        prepared = []
        seen = set()
        for line in lines:
            if not isinstance(line, dict):
                raise DomainError('INVALID_INPUT', '收貨品項格式錯誤', 400)
            line_id = line.get('shipment_item_id')
            if line_id in seen:
                raise DomainError('INVALID_INPUT', '同一品項不可重複核對', 400)
            seen.add(line_id)
            shipment_item = session.execute(db.select(ShipmentItem).where(
                ShipmentItem.id == line_id, ShipmentItem.shipment_id == shipment_id)
                .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
            if not shipment_item:
                raise DomainError('NOT_FOUND', '出貨品項不存在', 404)
            item, line_order = _item(session, shipment_item.order_item_id,
                actor_id, ('manager', 'admin'))
            if line_order.id != order.id:
                raise DomainError('NOT_FOUND', '出貨品項與訂單不符', 404)
            checked = quantity(line.get('checked_qty'), 1)
            sellable = quantity(line.get('sellable_qty'))
            damaged = quantity(line.get('damaged_qty'))
            short = quantity(line.get('short_qty'))
            if checked != sellable + damaged + short or \
                    checked > shipment_item.shipped_qty - shipment_item.checked_qty:
                raise DomainError('INVALID_QUANTITY', '核對量不符或超過待收量', 422)
            if (damaged or short) and not str(line.get('note') or '').strip():
                raise DomainError('INVALID_INPUT', '差異原因必填', 400)
            note = line.get('note')
            if note is not None:
                if not isinstance(note, str) or len(note) > 500:
                    raise DomainError('INVALID_INPUT', '收貨備註不得超過500字', 400)
                note = note.strip()
            prepared.append((shipment_item, item, checked, sellable, damaged, short,
                note))
        receipt = Receipt(store_id=order.store_id, user_id=actor_id,
            shipment_id=shipment_id, request_key=key, payload_hash=payload_hash,
            received_at=utc_naive(business_now()))
        session.add(receipt)
        session.flush()
        writer = get_provider('inventory_writer')
        for shipment_item, item, checked, sellable, damaged, short, note in prepared:
            row = ReceiptItem(receipt_id=receipt.id, shipment_item_id=shipment_item.id,
                checked_qty=checked, sellable_qty=sellable, damaged_qty=damaged,
                short_qty=short, inventory_source_id=f'receipt:{receipt.id}:{shipment_item.id}',
                note=note)
            session.add(row)
            session.flush()
            if sellable or damaged:
                inventory = session.execute(db.select(Inventory).where(
                    Inventory.store_id == order.store_id,
                    Inventory.product_id == item.product_id).execution_options(
                    populate_existing=True).with_for_update()).scalar_one()
                writer.apply_movement(mutation=InventoryMutation(order.store_id,
                    item.product_id, 'receipt', row.inventory_source_id,
                    sellable + damaged, damaged, inventory.version, actor_id,
                    business_now(), '核對收貨'), session=session)
            shipment_item.checked_qty += checked
            shipment_item.version += 1
            from app.services.tasks import create_task, complete_task
            if shipment_item.checked_qty == shipment_item.shipped_qty:
                complete_task(session, order.store_id, 'shipment_item',
                    str(shipment_item.id), 'receive_shipment', actor_id)
                complete_task(session, order.store_id, 'shipment_item',
                    str(shipment_item.id), 'investigate_shipment', actor_id,
                    {'resolved_by': 'receipt'})
            for kind, amount in (('damaged', damaged), ('short', short)):
                if amount:
                    parent = session.get(ReplacementAuthorization,
                        shipment_item.authorization_id) if shipment_item.authorization_id else None
                    variance = ReceiptVariance(receipt_item_id=row.id,
                        parent_variance_id=parent.variance_id if parent else None,
                        kind=kind,
                        quantity=amount, closed_qty=0, status='OPEN',
                        created_at=utc_naive(business_now()))
                    session.add(variance)
                    session.flush()
                    from app.services.tasks import policy_setting
                    variance_hours = policy_setting(session, order.store_id, item.product_id,
                        'variance_hours', 24)
                    create_task(session, order.store_id, 'operator', 'variance',
                        str(variance.id), 'resolve_variance',
                        business_now() + timedelta(hours=variance_hours), item.product_id)
            all_lines = session.execute(db.select(ShipmentItem).where(
                ShipmentItem.order_item_id == item.id).execution_options(
                populate_existing=True).with_for_update()).scalars().all()
            pending_receipt = any(s.checked_qty < s.shipped_qty for s in all_lines)
            pending_ship = _shipped(session, item.id) < item.committed_qty
            open_variance = session.execute(db.select(ReceiptVariance.id).join(ReceiptItem,
                ReceiptItem.id == ReceiptVariance.receipt_item_id).join(ShipmentItem,
                ShipmentItem.id == ReceiptItem.shipment_item_id).where(
                ShipmentItem.order_item_id == item.id,
                ReceiptVariance.status == 'OPEN').limit(1).with_for_update()).first() is not None
            item.status = 'PARTIALLY_RECEIVED' if pending_receipt or pending_ship \
                or open_variance else 'RECEIVED'
            _event(session, item, actor_id, 'RECEIVED', f'receipt_item:{row.id}',
                {'checked': checked, 'sellable': sellable, 'damaged': damaged,
                 'short': short, 'note': note})
            _changed(session, item, order, actor_id, 'fulfillment.receive', {},
                {'receipt_item_id': row.id})
        return receipt

    def mark_unknown(self, *, shipment_item_id, actor_id, reason, session):
        reason = _text(reason, '待查原因')
        line = session.get(ShipmentItem, shipment_item_id)
        if not line:
            raise DomainError('NOT_FOUND', '出貨品項不存在', 404)
        item, order = _item(session, line.order_item_id, actor_id, ('manager', 'admin'))
        line = session.execute(db.select(ShipmentItem).where(
            ShipmentItem.id == shipment_item_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        if line.checked_qty >= line.shipped_qty or line.eta_disputed:
            raise DomainError('INVALID_STATE', '此批次沒有可標記的待查量', 409)
        line.eta_disputed = True
        line.version += 1
        _event(session, item, actor_id, 'SHIPMENT_UNKNOWN',
            f'unknown:{line.id}:{line.version}', {'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.shipment_unknown',
            {}, {'shipment_item_id': line.id, 'reason': reason})
        from app.services.tasks import create_task, policy_setting
        minutes = policy_setting(session, order.store_id, item.product_id,
            'contact_minutes', 60)
        create_task(session, order.store_id, 'operator', 'shipment_item',
            str(line.id), 'investigate_shipment',
            business_now() + timedelta(minutes=minutes), item.product_id)
        return line

    def resolve_unknown(self, *, shipment_item_id, actor_id, eta, reason, session):
        reason = _text(reason, '確認結果')
        eta_value = _time(eta)
        line = session.get(ShipmentItem, shipment_item_id)
        if not line:
            raise DomainError('NOT_FOUND', '出貨品項不存在', 404)
        item, order = _item(session, line.order_item_id, actor_id, ('operator', 'admin'))
        line = session.execute(db.select(ShipmentItem).where(
            ShipmentItem.id == shipment_item_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        if not line.eta_disputed or line.checked_qty >= line.shipped_qty:
            raise DomainError('INVALID_STATE', '沒有待查的在途量', 409)
        if eta_value <= utc_naive(business_now()):
            raise DomainError('INVALID_ETA', '確認到貨時間須晚於現在', 422)
        previous_eta = line.eta
        line.eta = eta_value
        line.eta_disputed = False
        line.version += 1
        _event(session, item, actor_id, 'SHIPMENT_RECONFIRMED',
            f'reconfirmed:{line.id}:{line.version}', {'eta': eta, 'reason': reason,
                'previous_eta': aware(previous_eta).isoformat(),
                'previous_overdue': previous_eta < utc_naive(business_now())})
        _changed(session, item, order, actor_id, 'fulfillment.shipment_reconfirmed',
            {'disputed': True}, {'disputed': False, 'eta': eta})
        from app.services.tasks import complete_task, create_task, policy_setting
        complete_task(session, order.store_id, 'shipment_item', str(line.id),
            'investigate_shipment', actor_id, {'eta': eta, 'reason': reason})
        complete_task(session, order.store_id, 'shipment_item', str(line.id),
            'receive_shipment', actor_id, {'action': 'rescheduled', 'previous_eta': aware(previous_eta).isoformat(),
                'previous_overdue': previous_eta < utc_naive(business_now()), 'new_eta': eta})
        session.flush()
        create_task(session, order.store_id, 'manager', 'shipment_item', str(line.id),
            'receive_shipment', aware(eta_value) + timedelta(minutes=policy_setting(session,
                order.store_id, item.product_id, 'receipt_minutes', 60)), item.product_id)
        return line

    def propose_change(self, *, item_id, actor_id, committed_qty, eta,
                       reason, session):
        quantity(committed_qty)
        reason = _text(reason, '變更原因')
        eta_value = _time(eta)
        item, order = _item(session, item_id, actor_id, ('operator', 'admin'))
        _lock_store(session, order.store_id)
        if item.status not in ('SUBMITTED', 'ACCEPTED', 'PARTIALLY_SHIPPED',
                               'SHIPPED', 'PARTIALLY_RECEIVED'):
            raise DomainError('INVALID_STATE', '此品項不能變更', 409)
        if committed_qty < _shipped(session, item.id):
            raise DomainError('INVALID_QUANTITY', '新承諾不得低於已出貨量', 409)
        if committed_qty > item.original_qty and item.committed_qty == 0:
            raise DomainError('INVALID_QUANTITY', '首次提案不得超過原訂量', 422)
        if eta_value <= utc_naive(business_now()):
            raise DomainError('INVALID_ETA', 'ETA須晚於現在', 422)
        pending = session.execute(db.select(SupplyChangeRequest).where(
            SupplyChangeRequest.order_item_id == item.id,
            SupplyChangeRequest.status == 'PENDING').with_for_update()).scalar_one_or_none()
        if pending:
            raise DomainError('CHANGE_PENDING', '已有待回覆供貨提案', 409)
        old = {'committed_qty': item.committed_qty,
               'eta': aware(item.eta).isoformat() if item.eta else None,
               'status': item.status}
        new = {'committed_qty': committed_qty, 'eta': aware(eta_value).isoformat()}
        from app.services.tasks import policy_setting
        minutes = policy_setting(session, order.store_id, item.product_id,
            'supply_response_minutes', 60)
        change = SupplyChangeRequest(order_item_id=item.id, old_conditions=old,
            new_conditions=new, reason=reason, created_by=actor_id,
            created_at=utc_naive(business_now()),
            response_due_at=utc_naive(business_now() + timedelta(minutes=minutes)),
            status='PENDING')
        session.add(change)
        session.flush()
        if item.committed_qty == 0:
            item.status = 'CHANGE_PENDING'
        else:
            item.commitment_disputed = True
            item.disputed_qty = max(0, item.committed_qty - _shipped(session, item.id))
        _event(session, item, actor_id, 'CHANGE_PROPOSED', f'change:{change.id}',
            {'old': old, 'new': new, 'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.change_proposed', old, new)
        from app.services.tasks import create_task, complete_task
        if old['committed_qty'] == 0:
            complete_task(session, order.store_id, 'order_item', str(item.id),
                'respond_order', actor_id, {'proposal_id': change.id})
        create_task(session, order.store_id, 'manager', 'change', str(change.id),
            'respond_change', business_now() + timedelta(minutes=minutes), item.product_id)
        return change

    def request_cancel(self, *, item_id, actor_id, reason, session):
        reason = _text(reason, '取消原因')
        item, order = _item(session, item_id, actor_id, ('manager', 'admin'))
        if item.status not in ('ACCEPTED', 'PARTIALLY_SHIPPED',
                               'SHIPPED', 'PARTIALLY_RECEIVED'):
            raise DomainError('INVALID_STATE', '此品項不能提出取消', 409)
        pending = session.execute(db.select(SupplyChangeRequest.id).where(
            SupplyChangeRequest.order_item_id == item.id,
            SupplyChangeRequest.status == 'PENDING')).first()
        if pending:
            raise DomainError('CHANGE_PENDING', '已有待回覆提案', 409)
        shipped = _shipped(session, item.id)
        if shipped >= item.committed_qty:
            raise DomainError('INVALID_STATE', '已全數出貨，不能取消已出貨量', 409)
        old = {'committed_qty': item.committed_qty,
            'eta': aware(item.eta).isoformat(), 'status': item.status}
        new = {'committed_qty': shipped, 'eta': aware(item.eta).isoformat(),
            'kind': 'manager_cancel'}
        from app.services.tasks import create_task, policy_setting
        minutes = policy_setting(session, order.store_id, item.product_id,
            'supply_response_minutes', 60)
        change = SupplyChangeRequest(order_item_id=item.id, old_conditions=old,
            new_conditions=new, reason=reason, created_by=actor_id,
            created_at=utc_naive(business_now()),
            response_due_at=utc_naive(business_now() + timedelta(minutes=minutes)),
            status='PENDING')
        session.add(change)
        session.flush()
        item.commitment_disputed = True
        item.disputed_qty = item.committed_qty - shipped
        _event(session, item, actor_id, 'CANCELLATION_REQUESTED',
            f'cancel_request:{change.id}', {'reason': reason, 'new': new})
        _changed(session, item, order, actor_id, 'fulfillment.cancel_requested', old, new)
        create_task(session, order.store_id, 'operator', 'change', str(change.id),
            'respond_change', business_now() + timedelta(minutes=minutes), item.product_id)
        return change

    def respond_change(self, *, change_id, actor_id, accept, reason, session):
        if type(accept) is not bool:
            raise DomainError('INVALID_INPUT', '須明確接受或拒絕', 400)
        change = session.get(SupplyChangeRequest, change_id)
        if not change:
            raise DomainError('NOT_FOUND', '提案不存在', 404)
        responder_roles = ('operator', 'admin') if change.new_conditions.get('kind') == 'manager_cancel' \
            else ('manager', 'admin')
        if actor_id == change.created_by:
            raise DomainError('FORBIDDEN', '提案本人不能回覆自己的提案', 403)
        item, order = _item(session, change.order_item_id, actor_id,
            responder_roles)
        _lock_store(session, order.store_id)
        change = session.execute(db.select(SupplyChangeRequest).where(
            SupplyChangeRequest.id == change_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        if change.status != 'PENDING':
            raise DomainError('INVALID_STATE', '提案已回覆', 409)
        if not accept:
            reason = _text(reason, '拒絕原因')
        elif reason is None:
            reason = ''
        elif not isinstance(reason, str) or len(reason) > 500:
            raise DomainError('INVALID_INPUT', '回覆原因不得超過500字', 400)
        if accept:
            new_qty = change.new_conditions['committed_qty']
            if new_qty < _shipped(session, item.id):
                raise DomainError('INVALID_QUANTITY', '新承諾不得低於已出貨量', 409)
            item.committed_qty = new_qty
            item.eta = _time(change.new_conditions['eta'])
            item.cancelled_qty = max(0, item.original_qty - new_qty)
            if new_qty == 0:
                item.status = 'CANCELLED' if _shipped(session, item.id) == 0 else 'CLOSED_WITH_VARIANCE'
            elif _shipped(session, item.id) == 0:
                item.status = 'ACCEPTED'
            elif _shipped(session, item.id) < new_qty:
                item.status = 'PARTIALLY_SHIPPED'
            else:
                item.status = 'SHIPPED'
            received = session.execute(db.select(ReceiptItem.id).join(ShipmentItem,
                ShipmentItem.id == ReceiptItem.shipment_item_id).where(
                ShipmentItem.order_item_id == item.id).limit(1)).first()
            if received and new_qty > 0:
                item.status = 'PARTIALLY_RECEIVED'
            item.commitment_disputed = False
            item.disputed_qty = 0
        elif change.old_conditions['committed_qty'] == 0:
            item.status = 'CANCELLED'
        # Existing commitment remains disputed after rejection.
        change.status = 'ACCEPTED' if accept else 'REJECTED'
        change.responded_by = actor_id
        change.responded_at = utc_naive(business_now())
        change.response = {'reason': reason or '', 'accepted': accept}
        change.version += 1
        _event(session, item, actor_id, 'CHANGE_RESPONDED',
            f'change_response:{change.id}', {'accepted': accept, 'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.change_responded',
            change.old_conditions, change.new_conditions if accept else change.old_conditions)
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'change', str(change.id),
            'respond_change', actor_id, {'accepted': accept, 'reason': reason})
        if change.old_conditions['committed_qty'] == 0:
            complete_task(session, order.store_id, 'order_item', str(item.id),
                'respond_order', actor_id, {'proposal_accepted': accept})
        return change

    def reaffirm(self, *, item_id, actor_id, session):
        item, order = _item(session, item_id, actor_id, ('operator', 'admin'))
        if not item.commitment_disputed or session.execute(db.select(SupplyChangeRequest.id).where(
                SupplyChangeRequest.order_item_id == item.id,
                SupplyChangeRequest.status == 'PENDING')).first():
            raise DomainError('INVALID_STATE', '沒有可重申的既有承諾', 409)
        item.commitment_disputed = False
        item.disputed_qty = 0
        _event(session, item, actor_id, 'REAFFIRMED', f'reaffirm:{item.id}:{item.version}', {})
        _changed(session, item, order, actor_id, 'fulfillment.reaffirm',
            {'disputed': True}, {'disputed': False})
        return item

    def authorize_replacement(self, *, variance_id, actor_id, request_key,
                              quantity_value, eta, session):
        key = _text(request_key, '請求識別', 100)
        quantity(quantity_value, 1)
        eta_value = _time(eta)
        variance = session.get(ReceiptVariance, variance_id)
        receipt_item = session.get(ReceiptItem, variance.receipt_item_id) if variance else None
        line = session.get(ShipmentItem, receipt_item.shipment_item_id) if receipt_item else None
        if not line:
            raise DomainError('NOT_FOUND', '差異不存在', 404)
        item, order = _item(session, line.order_item_id, actor_id, ('operator', 'admin'))
        _lock_store(session, order.store_id)
        variance = session.execute(db.select(ReceiptVariance).where(
            ReceiptVariance.id == variance_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        payload_hash = _hash({'quantity': quantity_value, 'eta': eta})
        prior = session.execute(db.select(ReplacementAuthorization).where(
            ReplacementAuthorization.variance_id == variance_id,
            ReplacementAuthorization.request_key == key).execution_options(
            populate_existing=True).with_for_update()).scalar_one_or_none()
        if prior:
            if prior.payload_hash != payload_hash:
                raise DomainError('IDEMPOTENCY_CONFLICT', '相同識別的補送內容不同', 409)
            return prior
        used = sum(a.authorized_qty for a in session.execute(db.select(
            ReplacementAuthorization).where(ReplacementAuthorization.variance_id == variance_id)
            .execution_options(populate_existing=True).with_for_update()).scalars())
        if variance.status != 'OPEN' or quantity_value > variance.quantity - variance.closed_qty - used:
            raise DomainError('INVALID_QUANTITY', '補送額度不足', 409)
        if eta_value <= utc_naive(business_now()):
            raise DomainError('INVALID_ETA', 'ETA須晚於現在', 422)
        auth = ReplacementAuthorization(variance_id=variance_id, request_key=key,
            payload_hash=payload_hash, authorized_qty=quantity_value,
            used_qty=0, closed_qty=0, eta=eta_value, actor_id=actor_id,
            created_at=utc_naive(business_now()))
        session.add(auth)
        session.flush()
        _event(session, item, actor_id, 'REPLACEMENT_AUTHORIZED',
            f'replacement:{auth.id}', {'quantity': quantity_value, 'eta': eta})
        _changed(session, item, order, actor_id, 'fulfillment.replacement_authorized',
            {}, {'authorization_id': auth.id})
        return auth

    def close_variance(self, *, variance_id, actor_id, reason, session):
        reason = _text(reason, '結案原因')
        variance = session.get(ReceiptVariance, variance_id)
        receipt_item = session.get(ReceiptItem, variance.receipt_item_id) if variance else None
        line = session.get(ShipmentItem, receipt_item.shipment_item_id) if receipt_item else None
        if not line:
            raise DomainError('NOT_FOUND', '差異不存在', 404)
        item, order = _item(session, line.order_item_id, actor_id, ('operator', 'admin'))
        variance = session.execute(db.select(ReceiptVariance).where(
            ReceiptVariance.id == variance_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        auths = session.execute(db.select(ReplacementAuthorization).where(
            ReplacementAuthorization.variance_id == variance_id).execution_options(
            populate_existing=True).with_for_update()).scalars().all()
        in_flight = sum(a.used_qty - sum(s.checked_qty for s in session.execute(
            db.select(ShipmentItem).where(ShipmentItem.authorization_id == a.id)
            .execution_options(populate_existing=True).with_for_update()).scalars())
            for a in auths)
        if variance.status != 'OPEN' or in_flight:
            raise DomainError('INVALID_STATE', '補送仍在途或案件已結', 409)
        for auth in auths:
            auth.closed_qty = auth.authorized_qty - auth.used_qty
            auth.version += 1
        variance.closed_qty = max(0, variance.quantity - sum(a.used_qty for a in auths))
        variance.status = 'CLOSED'
        variance.resolved_at = utc_naive(business_now())
        variance.resolution = {'reason': reason}
        variance.version += 1
        pending = session.execute(db.select(ShipmentItem).where(
            ShipmentItem.order_item_id == item.id).execution_options(
            populate_existing=True).with_for_update()).scalars().all()
        other_open = session.execute(db.select(ReceiptVariance.id).join(ReceiptItem,
            ReceiptItem.id == ReceiptVariance.receipt_item_id).join(ShipmentItem,
            ShipmentItem.id == ReceiptItem.shipment_item_id).where(
            ShipmentItem.order_item_id == item.id, ReceiptVariance.id != variance.id,
            ReceiptVariance.status == 'OPEN').limit(1).with_for_update()).first() is not None
        if not other_open and all(s.checked_qty == s.shipped_qty for s in pending) and \
                _shipped(session, item.id) >= item.committed_qty:
            item.status = 'CLOSED_WITH_VARIANCE'
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'variance', str(variance.id),
            'resolve_variance', actor_id, {'reason': reason})
        _event(session, item, actor_id, 'VARIANCE_CLOSED',
            f'variance_close:{variance.id}', {'reason': reason})
        _changed(session, item, order, actor_id, 'fulfillment.variance_closed',
            {}, {'variance_id': variance.id, 'reason': reason})
        return variance

    def remove_damaged(self, *, variance_id, actor_id, request_key,
                       quantity_value, action, session):
        """Record disposal/return without changing the original receipt."""
        key = _text(request_key, '請求識別', 70)
        quantity(quantity_value, 1)
        if action not in ('discard', 'return'):
            raise DomainError('INVALID_INPUT', '處置方式須為報廢或退回', 400)
        variance = session.get(ReceiptVariance, variance_id)
        receipt_item = session.get(ReceiptItem, variance.receipt_item_id) if variance else None
        line = session.get(ShipmentItem, receipt_item.shipment_item_id) if receipt_item else None
        if not line:
            raise DomainError('NOT_FOUND', '差異不存在', 404)
        item, order = _item(session, line.order_item_id, actor_id, ('manager', 'admin'))
        variance = session.execute(db.select(ReceiptVariance).where(
            ReceiptVariance.id == variance_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        if variance.kind != 'damaged':
            raise DomainError('INVALID_STATE', '只有損壞實收可報廢或退回', 409)
        source = f'damaged:{variance_id}:{key}'
        prior = session.execute(db.select(FulfillmentEvent).where(
            FulfillmentEvent.source_key == source).with_for_update()).scalar_one_or_none()
        if prior:
            if prior.snapshot != {'quantity': quantity_value, 'action': action}:
                raise DomainError('IDEMPOTENCY_CONFLICT', '相同識別的處置內容不同', 409)
            return prior
        events = session.execute(db.select(FulfillmentEvent).where(
            FulfillmentEvent.order_item_id == item.id,
            FulfillmentEvent.event_type == 'DAMAGED_REMOVED').with_for_update()).scalars().all()
        removed = sum(e.snapshot['quantity'] for e in events
            if e.source_key.startswith(f'damaged:{variance_id}:'))
        if quantity_value > variance.quantity - removed:
            raise DomainError('INVALID_QUANTITY', '處置量超過損壞實收', 409)
        inventory = session.execute(db.select(Inventory).where(
            Inventory.store_id == order.store_id,
            Inventory.product_id == item.product_id).execution_options(
            populate_existing=True).with_for_update()).scalar_one()
        get_provider('inventory_writer').apply_movement(mutation=InventoryMutation(
            order.store_id, item.product_id, 'damaged_removal', source,
            -quantity_value, -quantity_value, inventory.version,
            actor_id, business_now(), '損壞品報廢' if action == 'discard' else '損壞品退回'),
            session=session)
        event = FulfillmentEvent(order_item_id=item.id, actor_id=actor_id,
            source_key=source, event_type='DAMAGED_REMOVED',
            occurred_at=utc_naive(business_now()),
            snapshot={'quantity': quantity_value, 'action': action})
        session.add(event)
        _changed(session, item, order, actor_id, 'fulfillment.damaged_removed',
            {}, {'variance_id': variance_id, 'quantity': quantity_value, 'action': action})
        session.flush()
        return event

    def report_extra(self, *, shipment_id, actor_id, request_key,
                     product_id, quantity_value, reason, session):
        """Quarantine an unrequested delivery without adding inventory."""
        key = _text(request_key, '請求識別', 70)
        quantity(product_id, 1)
        quantity(quantity_value, 1)
        reason = _text(reason, '多送原因')
        shipment = session.get(Shipment, shipment_id)
        order = session.get(Order, shipment.order_id) if shipment else None
        if not order:
            raise DomainError('NOT_FOUND', '出貨批次不存在', 404)
        anchor = session.execute(db.select(OrderItem.id).where(
            OrderItem.order_id == order.id).order_by(OrderItem.id).limit(1)).scalar_one_or_none()
        if anchor is None:
            raise DomainError('INVALID_STATE', '訂單沒有可追蹤品項', 409)
        item, order = _item(session, anchor, actor_id, ('manager', 'admin'))
        if session.get(Product, product_id) is None:
            raise DomainError('NOT_FOUND', '多送商品不存在', 404)
        source = f'extra:{shipment_id}:{key}'
        payload = {'shipment_id': shipment_id, 'product_id': product_id,
            'quantity': quantity_value, 'reason': reason,
            'inventory_effect': 0, 'status': 'QUARANTINED'}
        prior = session.execute(db.select(FulfillmentEvent).where(
            FulfillmentEvent.source_key == source).with_for_update()).scalar_one_or_none()
        if prior:
            if prior.snapshot != payload:
                raise DomainError('IDEMPOTENCY_CONFLICT', '相同識別的多送內容不同', 409)
            return prior
        event = FulfillmentEvent(order_item_id=item.id, actor_id=actor_id,
            source_key=source, event_type='EXTRA_HELD',
            occurred_at=utc_naive(business_now()), snapshot=payload)
        session.add(event)
        session.flush()
        _changed(session, item, order, actor_id, 'fulfillment.extra_held', {}, payload)
        from app.services.tasks import create_task, policy_setting
        hours = policy_setting(session, order.store_id, item.product_id,
            'variance_hours', 24)
        create_task(session, order.store_id, 'operator', 'extra_event', str(event.id),
            'resolve_extra', business_now() + timedelta(hours=hours), item.product_id)
        return event

    def resolve_extra(self, *, event_id, actor_id, action, reason, session):
        if action not in ('return', 'discard'):
            raise DomainError('INVALID_INPUT', '多送品須明確退回或報廢', 400)
        reason = _text(reason, '處理原因')
        held = session.get(FulfillmentEvent, event_id)
        if not held or held.event_type != 'EXTRA_HELD':
            raise DomainError('NOT_FOUND', '多送案件不存在', 404)
        item, order = _item(session, held.order_item_id,
            actor_id, ('operator', 'admin'))
        source = f'extra_resolution:{event_id}'
        if session.execute(db.select(FulfillmentEvent.id).where(
                FulfillmentEvent.source_key == source).with_for_update()).first():
            raise DomainError('INVALID_STATE', '多送案件已結案', 409)
        event = FulfillmentEvent(order_item_id=item.id, actor_id=actor_id,
            source_key=source, event_type='EXTRA_RESOLVED',
            occurred_at=utc_naive(business_now()),
            snapshot={'held_event_id': event_id, 'action': action,
                'reason': reason, 'inventory_effect': 0})
        session.add(event)
        _changed(session, item, order, actor_id, 'fulfillment.extra_resolved',
            held.snapshot, event.snapshot)
        from app.services.tasks import complete_task
        complete_task(session, order.store_id, 'extra_event', str(event_id),
            'resolve_extra', actor_id, event.snapshot)
        session.flush()
        return event


fulfillment_service = FulfillmentService()
