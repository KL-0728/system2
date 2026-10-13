from datetime import datetime
from flask import Blueprint, current_app, g, jsonify, render_template, request
from app.extensions import db
from app.models import AuditEvent
from app.services.access import require_role
from app.services.clock import business_now, set_clock
from app.services.errors import DomainError
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
    return jsonify({kind: [serialize(kind, r) for r in db.session.execute(
        db.select(model).order_by(model.id)).scalars()] for kind, model in MODELS.items()})


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
    page = request.args.get('page', type=int) if 'page' in request.args else 1
    if page is None or not 1 <= page <= 1000000:
        raise DomainError('INVALID_INPUT', '頁碼須為正整數', 400)
    query = db.select(AuditEvent)
    if request.args.get('action'):
        query = query.where(AuditEvent.action == request.args['action'])
    if request.args.get('store_id'):
        store_id = request.args.get('store_id', type=int)
        if store_id is None:
            raise DomainError('INVALID_INPUT', '門市須為整數', 400)
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
