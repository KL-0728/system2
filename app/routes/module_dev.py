from flask import Blueprint, current_app, g, render_template
from app.extensions import db
from app.providers import get_provider
from app.contracts import dto_dict
from app.services.clock import business_now, round_window
from app.services.access import require_role, authorize_store
from app.services.errors import DomainError
from app.models import Store, Product, Order, ReplenishmentRun

bp = Blueprint('module_dev', __name__)


@bp.get('/modules/<module>/')
@require_role()
def module_page(module):
    if module.upper() != current_app.config['MODULE_DEV']:
        raise DomainError('NOT_FOUND', '此模組開發模式未啟用', 404)
    if g.user.role == 'manager':
        store = next((s for s in g.user.stores if s.active), None)
    else:
        store = db.session.execute(db.select(Store).where(Store.active.is_(True)).order_by(Store.id)).scalars().first()
    if store is None:
        raise DomainError('NOT_FOUND', '無可用門市', 404)
    authorize_store(g.user, store.id)
    now = business_now()
    b, cutoff = round_window(now)
    from datetime import timedelta
    names = {'b': ('open_orders',), 'c': ('runs', 'integrity', 'open_orders', 'fulfillment'),
        'd': ('inventory_writer', 'orders')}[module]
    output = {}
    for name in names:
        provider = get_provider(name)
        if name == 'open_orders':
            output[name] = dto_dict(provider.get_open_orders(store_id=store.id, baseline_at=b,
                protection_end=b + timedelta(days=2), evaluated_at=now, session=db.session))
        elif name == 'runs':
            run = db.session.execute(db.select(ReplenishmentRun).where(ReplenishmentRun.store_id == store.id,
                ReplenishmentRun.model_version == 'controlled-test-v1')).scalars().first()
            output[name] = dto_dict(provider.get_run(run_id=run.id if run else 0, store_id=store.id,
                actor_id=g.user.id, session=db.session))
        elif name == 'integrity':
            product = db.session.execute(db.select(Product).order_by(Product.id)).scalars().first()
            output[name] = dto_dict(provider.get_integrity(store_id=store.id, product_id=product.id, baseline_at=b, session=db.session))
        elif name == 'fulfillment':
            output[name] = dto_dict(provider.get_summary(order_id=1, store_id=store.id, actor_id=g.user.id, session=db.session))
        elif name == 'orders':
            order = db.session.execute(db.select(Order).where(Order.store_id == store.id, Order.fixture_only.is_(True))).scalars().first()
            output[name] = dto_dict(provider.get_order(order_id=order.id, store_id=store.id, actor_id=g.user.id,
                session=db.session)) if order else {'message': '請先執行 seed-module D 建立測試訂單'}
        else:
            output[name] = {'message': '受控庫存寫入替身；GET 不寫入資料，請用合約測試驗證 rollback'}
    return render_template('module_dev.html', module=module.upper(), output=current_app.json.dumps(output,
        ensure_ascii=False, indent=2), sources=', '.join(names))
