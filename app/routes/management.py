from datetime import datetime
from flask import Blueprint, current_app, g, jsonify, render_template, request
from app.extensions import db
from app.models import AuditEvent
from app.services.access import require_role
from app.services.clock import business_now, set_clock
from app.services.errors import DomainError
from app.services.inputs import query_integer
from app.services.management import MODELS, POLICY_FIELDS, save, serialize, prepare_cycles
from app.services.version import transaction
from sqlalchemy.exc import IntegrityError

bp = Blueprint('management', __name__)


@bp.post('/api/admin/cycles/prepare')
@require_role('admin')
def cycles():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise DomainError('INVALID_INPUT', '請提供門市', 422)
    with transaction():
        result = prepare_cycles(g.user, data.get('store_id'))
    return jsonify(result)


@bp.get('/admin')
@require_role('admin')
def page():
    return render_template('admin.html', policy_fields=POLICY_FIELDS)


@bp.get('/api/admin/catalog')
@require_role('admin')
def catalog():
    kind = request.args.get('kind')
    if kind:
        if kind not in MODELS:
            raise DomainError('INVALID_INPUT', '管理分類無效', 400)
        page = query_integer('page', '頁碼', default=1, maximum=1_000_000)
        search = request.args.get('search', '').strip()
        if len(search) > 120:
            raise DomainError('INVALID_INPUT', '搜尋最多120字', 400)
        model = MODELS[kind]
        query = db.select(model)
        if search:
            columns = {'products': ('sku', 'name'), 'stores': ('code', 'name'), 'users': ('username',), 'policies': ()}[kind]
            if columns:
                query = query.where(db.or_(*(getattr(model, c).contains(search, autoescape=True) for c in columns)))
            elif search.isdigit():
                query = query.where(model.store_id == int(search))
            else:
                raise DomainError('INVALID_INPUT', '政策搜尋請填門市編號', 400)
        rows = db.session.execute(query.order_by(model.id).offset((page-1)*50).limit(51)).scalars().all()
        result = {k: [] for k in MODELS}
        result[kind] = [serialize(kind, r) for r in rows[:50]]
        # References remain compatible; fetch only necessary catalog types.
        for reference in ('stores', 'products'):
            if reference != kind:
                required = set()
                for row in rows[:50]:
                    if kind == 'policies':
                        required.add(row.store_id if reference == 'stores' else row.product_id)
                    elif kind == 'users' and reference == 'stores':
                        required.update(s.id for s in row.stores)
                lookup = MODELS[reference]
                first_ids = list(db.session.execute(db.select(lookup.id).order_by(lookup.id).limit(50)).scalars())
                references = db.session.execute(db.select(lookup).where(db.or_(
                    lookup.id.in_(first_ids), lookup.id.in_(required))).order_by(lookup.id)).scalars()
                result[reference] = [dict(id=r.id, name=r.name, active=r.active,
                    **({'sku':r.sku} if reference == 'products' else {'code':r.code})) for r in references]
        return jsonify(**result, page=page, has_next=len(rows)>50)
    return jsonify({kind: [serialize(kind, r) for r in db.session.execute(
        db.select(model).order_by(model.id)).scalars()] for kind, model in MODELS.items()})


@bp.get('/api/admin/lookups')
@require_role('admin')
def lookups():
    kind = request.args.get('kind')
    if kind not in ('products', 'stores'):
        raise DomainError('INVALID_INPUT', '參照分類無效', 400)
    value = request.args.get('search', '').strip()
    if len(value) > 120:
        raise DomainError('INVALID_INPUT', '搜尋最多120字', 400)
    model = MODELS[kind]
    code = model.sku if kind == 'products' else model.code
    query = db.select(model)
    if value:
        query = query.where(db.or_(code.contains(value, autoescape=True), model.name.contains(value, autoescape=True)))
    rows = db.session.execute(query.order_by(model.id).limit(51)).scalars().all()
    return jsonify(rows=[dict(id=r.id, label=f'{getattr(r, "sku", getattr(r,"code", ""))} · {r.name}')
        for r in rows[:50]], has_more=len(rows)>50)


@bp.post('/api/admin/<kind>')
@bp.patch('/api/admin/<kind>/<int:row_id>')
@require_role('admin')
def update(kind, row_id=None):
    try:
        with transaction():
            result = save(g.user, kind, request.get_json(silent=True), row_id)
    except IntegrityError as error:
        raise DomainError('DUPLICATE_RECORD', '代碼、帳號或門市商品已存在', 409) from error
    return jsonify(result), 200 if row_id else 201


@bp.get('/api/admin/audit')
@require_role('admin')
def audit():
    page = query_integer('page', '頁碼', default=1, maximum=1_000_000)
    query = db.select(AuditEvent)
    if request.args.get('action'):
        query = query.where(AuditEvent.action == request.args['action'])
    if request.args.get('store_id'):
        store_id = query_integer('store_id', '門市')
        query = query.where(AuditEvent.store_id == store_id)
    rows = db.session.execute(query.order_by(AuditEvent.id.desc()).offset((page-1)*50).limit(51)).scalars().all()
    return jsonify(page=page, has_next=len(rows)>50, events=[dict(id=r.id, actor_id=r.actor_id,
        store_id=r.store_id, action=r.action, entity=r.entity, old=r.old, new=r.new,
        server_time=r.server_time, business_time=r.business_time) for r in rows[:50]])


@bp.get('/api/admin/clock')
@require_role('admin')
def clock():
    return jsonify(time=business_now(), editable=current_app.config['APP_ENV'] != 'production')


@bp.post('/api/admin/clock')
@require_role('admin')
def clock_update():
    data = request.get_json(silent=True)
    try:
        target = datetime.fromisoformat(data['time'])
        if target.tzinfo is None or type(data.get('paused', True)) is not bool:
            raise ValueError()
    except (TypeError, KeyError, ValueError):
        raise DomainError('INVALID_INPUT', '時間須含時區，暫停須為布林值', 422)
    with transaction():
        set_clock(g.user, target, data.get('paused', True))
    return jsonify(time=business_now())
