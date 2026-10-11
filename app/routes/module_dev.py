from flask import Blueprint, current_app, g, render_template
from app.extensions import db
from app.providers import get_provider
from app.contracts import dto_dict
from app.services.clock import business_now, round_window
from app.services.access import require_role, authorize_store
from app.services.errors import DomainError
from app.models import Store, Product, Order
from app.services.run_sources import latest_run

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
    sources = []
    for name in names:
        provider = get_provider(name)
        test_only = current_app.extensions['service_providers'][name][1]
        sources.append(f'{name}: {"受控替身" if test_only else "真實服務"}')
        if name == 'open_orders':
            output[name] = dto_dict(provider.get_open_orders(store_id=store.id, baseline_at=b,
                protection_end=b + timedelta(days=2), evaluated_at=now, session=db.session))
        elif name == 'runs':
            run = latest_run(store.id)
            output[name] = dto_dict(provider.get_run(run_id=run.id, store_id=store.id,
                actor_id=g.user.id, session=db.session)) if run else {
                    'message': '目前沒有相容的計算快照。請先核對資料並由補貨頁產生本輪建議。',
                    'prepare_url': f'/store/replenishment?store_id={store.id}'}
        elif name == 'integrity':
            product = db.session.execute(db.select(Product).order_by(Product.id)).scalars().first()
            output[name] = dto_dict(provider.get_integrity(store_id=store.id, product_id=product.id, baseline_at=b, session=db.session))
        elif name == 'fulfillment':
            statement = db.select(Order).where(Order.store_id == store.id)
            if not test_only:
                statement = statement.where(Order.fixture_only.is_(False))
            order = db.session.execute(statement.order_by(Order.id.desc())).scalars().first()
            output[name] = dto_dict(provider.get_summary(order_id=order.id, store_id=store.id,
                actor_id=g.user.id, session=db.session)) if order else {
                    'message': '本門市尚無可查詢的訂單；不使用其他門市或工廠訂單冒充正式履約。'}
        elif name == 'orders':
            order = db.session.execute(db.select(Order).where(Order.store_id == store.id, Order.fixture_only.is_(True))).scalars().first()
            output[name] = {'data': dto_dict(provider.get_order(order_id=order.id, store_id=store.id, actor_id=g.user.id,
                session=db.session)), 'data_source': '明示 D 獨立開發用工廠訂單，非正式送單'} \
                if order else {'message': '請先執行 seed-module D 建立測試訂單'}
        else:
            output[name] = {'message': 'GET 不寫入庫存。請用同交易測試驗證回滾、來源唯一性與冪等；既有替身異動不得冒充正式入帳。'}
    return render_template('module_dev.html', module=module.upper(), output=current_app.json.dumps(output,
        ensure_ascii=False, indent=2), sources='；'.join(sources))
