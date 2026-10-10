from flask import Blueprint, g, jsonify, render_template, request

from app.contracts import dto_dict
from app.extensions import db
from app.models import Order, OrderDraft, Product, ReplenishmentRun, Store
from app.providers import get_provider
from app.services.access import authorize_store, require_role
from app.services.errors import DomainError
from app.services.orders import INTRO_VERSION, ordering_service
from app.services.version import transaction


bp = Blueprint('ordering', __name__)


def _payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise DomainError('INVALID_INPUT', '請提供 JSON 物件', 400)
    return value


def _manager_store(store_id=None):
    if store_id is not None:
        return authorize_store(g.user, store_id, roles=('manager', 'admin'))
    if g.user.role == 'manager':
        store = next((row for row in g.user.stores if row.active), None)
    else:
        store = db.session.execute(db.select(Store).where(Store.active.is_(True))
            .order_by(Store.id)).scalars().first()
    if store is None:
        raise DomainError('NOT_FOUND', '沒有可操作的門市', 404)
    return authorize_store(g.user, store.id, roles=('manager', 'admin'))


@bp.get('/store/ordering')
@require_role('manager', 'admin')
def ordering_page():
    store = _manager_store(request.args.get('store_id', type=int))
    run = db.session.execute(db.select(ReplenishmentRun).where(
        ReplenishmentRun.store_id == store.id).order_by(
        ReplenishmentRun.actual_generated_at.desc(), ReplenishmentRun.id.desc())).scalars().first()
    run_data = None
    if run:
        run_data = dto_dict(get_provider('runs').get_run(run_id=run.id, store_id=store.id,
            actor_id=g.user.id, session=db.session))
        products = {row.id: row for row in db.session.execute(db.select(Product).where(
            Product.id.in_([item['product_id'] for item in run_data['items']]))).scalars()}
        for item in run_data['items']:
            product = products[item['product_id']]
            item.update(sku=product.sku, name=product.name, unit=product.base_unit)
    return render_template('store/ordering.html', store=store, run=run_data,
        intro_version=INTRO_VERSION,
        intro_status=ordering_service.acknowledgement_status(g.user))


@bp.get('/store/orders')
@require_role('manager', 'admin')
def orders_page():
    store = _manager_store(request.args.get('store_id', type=int))
    return render_template('store/orders.html', store=store)


@bp.get('/store/orders/<int:order_id>')
@require_role('manager', 'admin')
def order_page(order_id):
    store = _manager_store(request.args.get('store_id', type=int))
    order = db.session.get(Order, order_id)
    if not order or order.store_id != store.id or order.fixture_only:
        raise DomainError('NOT_FOUND', '訂單不存在', 404)
    return render_template('store/order_detail.html', store=store, order_id=order_id,
        order_number=order.number)


@bp.get('/api/ordering/acknowledgement')
@require_role('manager', 'admin')
def acknowledgement_status():
    return jsonify(ordering_service.acknowledgement_status(g.user))


@bp.post('/api/ordering/acknowledgement')
@require_role('manager', 'admin')
def acknowledge_intro():
    data = _payload()
    with transaction():
        result = ordering_service.acknowledge_intro(g.user, data.get('acknowledged'))
    return jsonify(result)


@bp.get('/api/stores/current/dashboard')
@require_role('manager', 'admin')
def dashboard():
    store = _manager_store(request.args.get('store_id', type=int))
    latest_run = db.session.execute(db.select(ReplenishmentRun).where(
        ReplenishmentRun.store_id == store.id).order_by(
        ReplenishmentRun.actual_generated_at.desc(), ReplenishmentRun.id.desc())).scalars().first()
    drafts = db.session.execute(db.select(OrderDraft).where(OrderDraft.store_id == store.id,
        OrderDraft.user_id == g.user.id, OrderDraft.status == 'DRAFT').order_by(
        OrderDraft.updated_at.desc())).scalars().all()
    orders = db.session.execute(db.select(Order).where(Order.store_id == store.id,
        Order.fixture_only.is_(False)).order_by(Order.submitted_at.desc()).limit(10)).scalars().all()
    return jsonify(store={'id': store.id, 'code': store.code, 'name': store.name,
            'calculation_version': store.calculation_version},
        acknowledgement=ordering_service.acknowledgement_status(g.user),
        latest_run_id=latest_run.id if latest_run else None,
        drafts=[{'id': row.id, 'version': row.version, 'run_id': row.run_id,
            'cycle_id': row.cycle_id, 'updated_at': row.updated_at} for row in drafts],
        orders=[{'id': row.id, 'number': row.number, 'status': row.status,
            'submitted_at': row.submitted_at} for row in orders])


@bp.post('/api/order-drafts')
@require_role('manager', 'admin')
def create_draft():
    data = _payload()
    store = _manager_store(data.get('store_id'))
    with transaction():
        result = ordering_service.create_draft(g.user, store_id=store.id,
            run_id=data.get('run_id'), cycle_id=data.get('cycle_id'),
            final_quantities=None)
    return jsonify(result), 201


@bp.get('/api/order-drafts/<int:draft_id>')
@require_role('manager', 'admin')
def get_draft(draft_id):
    return jsonify(ordering_service.get_draft(g.user, draft_id))


@bp.patch('/api/order-drafts/<int:draft_id>')
@require_role('manager', 'admin')
def update_draft(draft_id):
    with transaction():
        result = ordering_service.update_draft(g.user, draft_id, _payload())
    return jsonify(result)


@bp.post('/api/order-drafts/<int:draft_id>/preview')
@require_role('manager', 'admin')
def preview(draft_id):
    data = _payload()
    with transaction():
        result = ordering_service.preview(g.user, draft_id, data.get('expected_version'))
    return jsonify(result)


@bp.post('/api/order-drafts/<int:draft_id>/submit')
@require_role('manager', 'admin')
def submit(draft_id):
    with transaction():
        result = ordering_service.submit(g.user, draft_id, _payload(),
            request.headers.get('Idempotency-Key'))
    return jsonify(result), 200 if result['replayed'] else 201


@bp.get('/api/submissions/<key>')
@require_role('manager', 'admin')
def submission(key):
    store = _manager_store(request.args.get('store_id', type=int))
    return jsonify(ordering_service.submission_result(g.user, store.id, key))


@bp.get('/api/orders')
@require_role('manager', 'admin')
def list_orders():
    store = _manager_store(request.args.get('store_id', type=int))
    rows = db.session.execute(db.select(Order).where(Order.store_id == store.id,
        Order.fixture_only.is_(False)).order_by(Order.submitted_at.desc(), Order.id.desc())).scalars().all()
    return jsonify(orders=[{'id': row.id, 'number': row.number, 'status': row.status,
        'version': row.version, 'submitted_at': row.submitted_at} for row in rows])


def _order_detail(order_id, include_fulfillment=True):
    store = _manager_store(request.args.get('store_id', type=int))
    value = dto_dict(ordering_service.get_order(order_id=order_id, store_id=store.id,
        actor_id=g.user.id, session=db.session))
    if include_fulfillment:
        value['fulfillment'] = dto_dict(get_provider('fulfillment').get_summary(
            order_id=order_id, store_id=store.id, actor_id=g.user.id, session=db.session))
    return value


@bp.get('/api/orders/<int:order_id>')
@require_role('manager', 'admin')
def get_order(order_id):
    return jsonify(_order_detail(order_id))


@bp.get('/api/orders/<int:order_id>/decision-record')
@require_role('manager', 'admin')
def decision_record(order_id):
    return jsonify(_order_detail(order_id, include_fulfillment=False))
