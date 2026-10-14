from flask import Blueprint
from inspect import signature, Parameter
bp = Blueprint('fulfillment', __name__)
# D owns this blueprint.
from flask import current_app, g, jsonify, render_template, request
from app.contracts import dto_dict
from app.extensions import db
from app.models import (Order, OrderItem, Shipment, ShipmentItem, Store,
    ReceiptVariance, ReceiptItem, SupplyChangeRequest, ReplacementAuthorization,
    User, Product)
from app.services.access import authorize_store, require_role
from app.services.errors import DomainError
from app.services.inputs import query_integer
from app.services.clock import aware
from app.services.fulfillment import fulfillment_service
from app.services.tasks import list_tasks, request_contact, resolve_contact
from app.services.version import transaction


def _body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise DomainError('INVALID_INPUT', '請提供 JSON 物件', 400)
    return value


def _store_id():
    store_id = query_integer('store_id', '門市')
    if store_id is None and g.user.role == 'manager':
        store_id = next((s.id for s in g.user.stores if s.active), None)
    if store_id is None:
        raise DomainError('INVALID_INPUT', '請指定門市', 400)
    authorize_store(g.user, store_id)
    return store_id


@bp.get('/headquarters/fulfillment')
@require_role('operator', 'admin')
def headquarters_page():
    return render_template('headquarters/fulfillment.html')


@bp.get('/store/receiving')
@require_role('manager', 'admin')
def receiving_page():
    store_id = query_integer('store_id', '門市')
    if store_id is None:
        target = next((s for s in g.user.stores if s.active), None) if g.user.role == 'manager' else \
            db.session.execute(db.select(Store).where(Store.active.is_(True)).order_by(Store.id)).scalars().first()
        store_id = target.id if target else None
    store = authorize_store(g.user, store_id, roles=('manager', 'admin'))
    return render_template('store/receiving.html', store=store)


@bp.get('/api/fulfillment/stores')
@require_role('manager', 'operator', 'admin')
def stores():
    rows = db.session.execute(db.select(Store).where(Store.active.is_(True))
        .order_by(Store.id)).scalars().all()
    return jsonify(stores=[dict(id=s.id, code=s.code, name=s.name) for s in rows
        if g.user.role != 'manager' or s in g.user.stores])


@bp.get('/api/fulfillment/products')
@require_role('manager', 'operator', 'admin')
def products():
    rows = db.session.execute(db.select(Product).order_by(Product.name)).scalars().all()
    return jsonify(products=[dict(id=p.id, sku=p.sku, name=p.name) for p in rows])


@bp.get('/api/fulfillment/orders')
@require_role('manager', 'operator', 'admin')
def orders():
    store_id = _store_id()
    page = query_integer('page', '頁碼', default=1, maximum=1_000_000)
    query = db.select(Order).where(Order.store_id == store_id)
    if current_app.config['MODULE_DEV'] != 'D':
        query = query.where(Order.fixture_only.is_(False))
    from app.services.order_filters import filtered
    query = filtered(query)
    rows = db.session.execute(query.order_by(Order.id.desc()).offset((page-1)*100).limit(101)).scalars().all()
    return jsonify(orders=[dict(id=o.id, number=o.number, status=o.status,
        submitted_at=aware(o.submitted_at).isoformat(), store_id=o.store_id,
        fixture_only=o.fixture_only) for o in rows[:100]], page=page, has_next=len(rows)>100)


@bp.get('/api/fulfillment/orders/<int:order_id>')
@require_role('manager', 'operator', 'admin')
def order_detail(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        raise DomainError('NOT_FOUND', '訂單不存在', 404)
    authorize_store(g.user, order.store_id)
    if order.fixture_only and current_app.config['MODULE_DEV'] != 'D':
        raise DomainError('NOT_FOUND', '此為獨立開發測試訂單', 404)
    summary = dto_dict(fulfillment_service.get_summary(order_id=order_id,
        store_id=order.store_id, actor_id=g.user.id, session=db.session))
    shipments = db.session.execute(db.select(Shipment).where(
        Shipment.order_id == order_id).order_by(Shipment.id)).scalars().all()
    summary['shipments'] = [dict(id=s.id, shipped_at=aware(s.shipped_at).isoformat(),
        lines=[dict(id=l.id, item_id=l.order_item_id, kind=l.kind,
            shipped_qty=l.shipped_qty, checked_qty=l.checked_qty,
            eta=aware(l.eta).isoformat(), eta_disputed=l.eta_disputed) for l in db.session.execute(
            db.select(ShipmentItem).where(ShipmentItem.shipment_id == s.id)).scalars()])
        for s in shipments]
    summary['fixture_only'] = order.fixture_only
    summary['number'] = order.number
    summary['status'] = order.status
    changes = db.session.execute(db.select(SupplyChangeRequest).join(OrderItem,
        SupplyChangeRequest.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order_id)
        .order_by(SupplyChangeRequest.id)).scalars().all()
    summary['changes'] = [dict(id=c.id, item_id=c.order_item_id, status=c.status,
        new_conditions=c.new_conditions, reason=c.reason,
        due_at=aware(c.response_due_at).isoformat(),
        initiator_role=db.session.get(User, c.created_by).role) for c in changes]
    variances = db.session.execute(db.select(ReceiptVariance).join(ReceiptItem,
        ReceiptItem.id == ReceiptVariance.receipt_item_id).join(ShipmentItem,
        ShipmentItem.id == ReceiptItem.shipment_item_id).join(Shipment,
        Shipment.id == ShipmentItem.shipment_id).where(Shipment.order_id == order_id)
        .order_by(ReceiptVariance.id)).scalars().all()
    summary['variances'] = [dict(id=v.id, kind=v.kind, quantity=v.quantity,
        closed_qty=v.closed_qty, status=v.status,
        parent_variance_id=v.parent_variance_id,
        item_id=db.session.get(ShipmentItem,
            db.session.get(ReceiptItem, v.receipt_item_id).shipment_item_id).order_item_id)
        for v in variances]
    auths = db.session.execute(db.select(ReplacementAuthorization).where(
        ReplacementAuthorization.variance_id.in_([v.id for v in variances]))
        .order_by(ReplacementAuthorization.id)).scalars().all() if variances else []
    summary['authorizations'] = [dict(id=a.id, variance_id=a.variance_id,
        authorized_qty=a.authorized_qty, used_qty=a.used_qty,
        closed_qty=a.closed_qty, eta=aware(a.eta).isoformat()) for a in auths]
    return jsonify(summary)


@bp.get('/api/fulfillment/tasks')
@require_role('manager', 'operator', 'admin')
def tasks():
    store_id = _store_id()
    return jsonify(tasks=list_tasks(db.session, store_id, g.user.role))


@bp.post('/api/fulfillment/stores/<int:store_id>/contacts')
@require_role('manager')
def contact(store_id):
    body = _body()
    with transaction() as session:
        task = request_contact(session, store_id, g.user.id, body.get('reason'), body.get('request_key'))
        session.flush()
        task_id = task.id
    return jsonify(id=task_id, status='ok')


@bp.post('/api/fulfillment/contacts/<int:task_id>/resolve')
@require_role('manager')
def contact_result(task_id):
    body = _body()
    with transaction() as session:
        task = resolve_contact(session, task_id, g.user.id, body.get('result'), body.get('request_key'))
    return jsonify(id=task.id, status='ok')


def _mutate(method, **ids):
    body = _body()
    parameters = signature(method).parameters
    allowed = set(parameters) - {'actor_id', 'session'} - set(ids)
    allowed.add('expected_version')
    allowed.add('request_key')
    required = {name for name, p in parameters.items()
        if p.default is Parameter.empty} - {'actor_id', 'session'} - set(ids)
    if set(body) - allowed or required - set(body):
        raise DomainError('INVALID_INPUT', '履約欄位缺漏或包含不支援的欄位', 422)
    with transaction() as session:
        from app.services.fulfillment_requests import check_precondition
        command_hash = None
        command_key = body.get('request_key')
        if command_key is not None and 'request_key' not in parameters:
            from app.services.fulfillment import _hash, _text
            command_key = _text(command_key, '請求識別', 100)
            command_hash = _hash({'action':method.__name__, 'ids':ids,
                'body':{k:v for k,v in body.items() if k not in ('expected_version', 'request_key')}})
        order, saved = check_precondition(g.user, method.__name__, ids, body, session, command_hash)
        if saved:
            return jsonify(id=saved.result_id, status='ok')
        if command_hash:
            body.pop('request_key')
        result = method(actor_id=g.user.id, session=session, **ids, **body)
        session.flush()
        result_id = result.id
        if command_hash:
            from app.models import FulfillmentCommand
            session.add(FulfillmentCommand(order_id=order.id, actor_id=g.user.id, request_key=command_key,
                payload_hash=command_hash, result_id=result_id, action=method.__name__))
    return jsonify(id=result_id, status='ok')


@bp.post('/api/fulfillment/items/<int:item_id>/accept')
@require_role('operator', 'admin')
def accept(item_id):
    return _mutate(fulfillment_service.accept, item_id=item_id)


@bp.post('/api/fulfillment/items/<int:item_id>/reject')
@require_role('operator', 'admin')
def reject(item_id):
    return _mutate(fulfillment_service.reject, item_id=item_id)


@bp.post('/api/fulfillment/items/<int:item_id>/cancel')
@require_role('manager', 'admin')
def cancel_pending(item_id):
    return _mutate(fulfillment_service.cancel_pending, item_id=item_id)


@bp.post('/api/fulfillment/orders/<int:order_id>/shipments')
@require_role('operator', 'admin')
def ship(order_id):
    return _mutate(fulfillment_service.ship, order_id=order_id)


@bp.post('/api/fulfillment/shipments/<int:shipment_id>/receipts')
@require_role('manager', 'admin')
def receive(shipment_id):
    return _mutate(fulfillment_service.receive, shipment_id=shipment_id)


@bp.post('/api/fulfillment/shipment-items/<int:shipment_item_id>/unknown')
@require_role('manager', 'admin')
def mark_unknown(shipment_item_id):
    return _mutate(fulfillment_service.mark_unknown, shipment_item_id=shipment_item_id)


@bp.post('/api/fulfillment/shipment-items/<int:shipment_item_id>/resolve')
@require_role('operator', 'admin')
def resolve_unknown(shipment_item_id):
    return _mutate(fulfillment_service.resolve_unknown, shipment_item_id=shipment_item_id)


@bp.post('/api/fulfillment/items/<int:item_id>/changes')
@require_role('operator', 'admin')
def propose_change(item_id):
    return _mutate(fulfillment_service.propose_change, item_id=item_id)


@bp.post('/api/fulfillment/items/<int:item_id>/cancel-request')
@require_role('manager', 'admin')
def request_cancel(item_id):
    return _mutate(fulfillment_service.request_cancel, item_id=item_id)


@bp.post('/api/fulfillment/changes/<int:change_id>/response')
@require_role('manager', 'operator', 'admin')
def respond_change(change_id):
    return _mutate(fulfillment_service.respond_change, change_id=change_id)


@bp.post('/api/fulfillment/items/<int:item_id>/reaffirm')
@require_role('operator', 'admin')
def reaffirm(item_id):
    return _mutate(fulfillment_service.reaffirm, item_id=item_id)


@bp.post('/api/fulfillment/variances/<int:variance_id>/authorizations')
@require_role('operator', 'admin')
def authorize_replacement(variance_id):
    return _mutate(fulfillment_service.authorize_replacement, variance_id=variance_id)


@bp.post('/api/fulfillment/variances/<int:variance_id>/close')
@require_role('operator', 'admin')
def close_variance(variance_id):
    return _mutate(fulfillment_service.close_variance, variance_id=variance_id)


@bp.post('/api/fulfillment/variances/<int:variance_id>/damaged-removal')
@require_role('manager', 'admin')
def remove_damaged(variance_id):
    return _mutate(fulfillment_service.remove_damaged, variance_id=variance_id)


@bp.post('/api/fulfillment/shipments/<int:shipment_id>/extra')
@require_role('manager', 'admin')
def report_extra(shipment_id):
    return _mutate(fulfillment_service.report_extra, shipment_id=shipment_id)


@bp.post('/api/fulfillment/extra/<int:event_id>/resolve')
@require_role('operator', 'admin')
def resolve_extra(event_id):
    return _mutate(fulfillment_service.resolve_extra, event_id=event_id)


from app.modules.fulfillment.demo import register_demo
register_demo(bp)
