"""B-owned run endpoints; canonical v1 paths and session-scoped provider calls."""
from flask import g, jsonify, render_template, request
from app.contracts import dto_dict, quantity
from app.extensions import db
from app.models import DeliveryCycle, ReplenishmentRun
from app.services.access import require_role
from app.services.clock import aware, round_window
from app.services.errors import DomainError
from app.services.inventory import _business_now
from app.services.replenishment import ReplenishmentService, authorize
from app.services.version import transaction


def register_replenishment(bp):
    service = ReplenishmentService()

    def store_id(value=None):
        if value is None:
            store = next((s for s in g.user.stores if s.active), None)
            if store is None:
                raise DomainError('INVALID_INPUT', '請指定門市id', 400)
            value = store.id
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        quantity(value, minimum=1, maximum=2_147_483_647)
        return value

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise DomainError('INVALID_INPUT', '請提供JSON物件', 400)
        return data

    @bp.get('/store/replenishment')
    @require_role('manager', 'admin')
    def replenishment_page():
        store = authorize(db.session, store_id(request.args.get('store_id')), g.user.id)
        return render_template('inventory/replenishment.html', store=store)

    @bp.get('/api/replenishment/context')
    @require_role('manager', 'admin')
    def replenishment_context():
        with transaction():
            store = authorize(db.session, store_id(request.args.get('store_id')), g.user.id, lock=True)
            now = _business_now(db.session)
            b, cutoff = round_window(now)
            cycles = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id == store.id,
                DeliveryCycle.baseline_at == b.replace(tzinfo=None), DeliveryCycle.cancelled.is_(False))
                .order_by(DeliveryCycle.arrival_at)).scalars().all()
            runs = db.session.execute(db.select(ReplenishmentRun).where(ReplenishmentRun.store_id == store.id)
                .order_by(ReplenishmentRun.id.desc()).limit(30)).scalars().all()
            from flask import current_app
            provider = current_app.extensions['service_providers'].get('open_orders')
            result = dict(store_id=store.id, store_version=store.calculation_version, business_now=now,
                baseline_at=b, cutoff_at=cutoff, can_generate=b <= now < cutoff,
                source_provider=dict(name=type(provider[0]).__name__ if provider else '尚未接入',
                    test_only=provider[1] if provider else False),
                cycles=[dict(id=c.id, arrival_at=aware(c.arrival_at),
                    lead_days=(aware(c.arrival_at) - b).days) for c in cycles],
                runs=[dict(id=r.id, baseline_at=aware(r.baseline_at), actual_generated_at=aware(r.actual_generated_at))
                    for r in runs])
        return jsonify(result)

    @bp.post('/api/replenishment/runs')
    @require_role('manager', 'admin')
    def generate_run():
        data = payload()
        with transaction():
            result = service.generate(store_id=store_id(data.get('store_id')), actor_id=g.user.id,
                cycle_id=data.get('cycle_id'), expected_version=data.get('expected_version'), session=db.session)
        return jsonify(dto_dict(result)), 201

    @bp.get('/api/replenishment/runs/<int:run_id>')
    @require_role('manager', 'admin')
    def read_run(run_id):
        with transaction():
            result = service.get_run(run_id=run_id, store_id=store_id(request.args.get('store_id')),
                                     actor_id=g.user.id, session=db.session)
        return jsonify(dto_dict(result))

    @bp.post('/api/replenishment/runs/<int:run_id>/evaluate')
    @require_role('manager', 'admin')
    def evaluate_run(run_id):
        data = payload()
        values = data.get('final_quantities')
        if not isinstance(values, dict) or any(not k.isascii() or not k.isdecimal() for k in values):
            raise DomainError('INVALID_INPUT', '請以商品id對應整數件數', 400)
        if len({int(k) for k in values}) != len(values):
            raise DomainError('INVALID_INPUT', '商品id不得重複', 400)
        with transaction():
            result = service.evaluate(run_id=run_id, store_id=store_id(data.get('store_id')), actor_id=g.user.id,
                cycle_id=data.get('cycle_id'), final_quantities={int(k): v for k, v in values.items()},
                manual_confirmations=(), evaluated_at=_business_now(db.session), session=db.session)
        return jsonify(dto_dict(result))
