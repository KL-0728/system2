"""Add an isolated B/C demo through real B accounting and run services."""
import csv
import os
from datetime import time, timedelta
from io import StringIO
from flask import current_app
from app.config import validate_database
from app.extensions import db
from app.models import Store, User, Product, PolicyVersion, StoreProduct, Inventory, DeliveryCycle
from app.providers import get_provider
from app.seed import POLICY
from app.services.clock import business_now, round_window, utc_naive, TAIPEI
from app.services.errors import DomainError
from app.services.sales import SalesService, COLUMNS
from app.services.replenishment import ReplenishmentService


def prepare_ordering_demo(session):
    if current_app.config['APP_ENV'] != 'demo' or current_app.config['MODULE_DEV'] not in ('', 'B', 'C'):
        raise ValueError('僅限本機 demo、整合模式或 MODULE_DEV=B／C；不允許 test 或正式環境')
    validate_database(session.get_bind().engine.url.render_as_string(hide_password=False), 'demo')
    for name in ('runs', 'integrity', 'inventory_writer'):
        get_provider(name)
        if current_app.extensions['service_providers'][name][1]:
            raise ValueError('此案例必須使用正式 B 計算與庫存服务')
    # D can still be explicitly controlled in module mode; never hide that fact.
    get_provider('open_orders')
    existing = session.execute(db.select(Store).where(Store.code == 'BCDEMO')).scalar_one_or_none()
    if existing:
        return f'BCDEMO 已存在（門市id={existing.id}），保留全部資料、密碼與時鐘；帳號 bcmanager。'
    if session.execute(db.select(User.id).where(User.username == 'bcmanager')).first():
        raise ValueError('bcmanager 已存在，拒絕覆寫帳號')
    password = os.environ.get('DEMO_PASSWORD', '')
    if len(password) < 8 or password.startswith('REPLACE_'):
        raise ValueError('請設定本機 DEMO_PASSWORD，不覆寫既有帳號')
    now = business_now()
    b, cutoff = round_window(now)
    if not b <= now < cutoff:
        raise DomainError('ROUND_NOT_OPEN', '示範業務時間須在21:00–22:00；本指令不修改時鐘', 409)
    products = session.execute(db.select(Product).where(Product.active.is_(True))
        .order_by(Product.id).limit(10)).scalars().all()
    if not products:
        raise ValueError('請先準備商品與基準示範資料')
    store = Store(code='BCDEMO', name='B與C合成整合示範門市', cutoff=time(22))
    session.add(store)
    session.flush()
    actor = User(username='bcmanager', role='manager', stores=[store])
    actor.set_password(password)
    session.add(actor)
    session.flush()
    stocks = []
    for product in products:
        policy = PolicyVersion(store_id=store.id, product_id=product.id, version=1,
            effective_at=utc_naive(b), parameters={**POLICY, 'lead_days': 1,
                'safety_stock': 10, 'capacity': 100, 'pack_size': product.pack_size})
        session.add(policy)
        session.flush()
        session.add(StoreProduct(store_id=store.id, product_id=product.id,
            policy_version_id=policy.id, lead_days=1, safety_stock=10, capacity=100))
        # Synthetic opening balance; current-day sales and count use real B.
        stock = Inventory(store_id=store.id, product_id=product.id, physical_qty=40,
            unsellable_qty=0, book_physical_qty=40, book_unsellable_qty=0,
            counted_at=utc_naive(b - timedelta(days=1)), updated_at=utc_naive(now))
        session.add(stock)
        stocks.append(stock)
    cycle = DeliveryCycle(store_id=store.id, baseline_at=utc_naive(b), cutoff_at=utc_naive(cutoff),
        arrival_at=utc_naive(b + timedelta(days=1)))
    session.add(cycle)
    session.flush()
    text = StringIO()
    writer = csv.writer(text)
    writer.writerow(COLUMNS)
    for product in products:
        for days in range(1, 7):
            writer.writerow(('BCDEMO-HISTORY', store.code, product.sku,
                (b - timedelta(days=days)).astimezone(TAIPEI).date().isoformat(), 20, '0', '1'))
    payload = dict(store_id=store.id, import_mode='historical', csv_text=text.getvalue())
    sales = SalesService()
    validation = sales.validate(payload=payload, actor_id=actor.id, session=session)
    if not validation['valid']:
        raise DomainError('CSV_INVALID', '合成歷史資料驗證失敗', details=validation['errors'])
    sales.commit(payload=payload, actor_id=actor.id, validation_token=validation['validation_token'], session=session)
    daily = StringIO()
    writer = csv.writer(daily)
    writer.writerow(COLUMNS)
    for product in products:
        writer.writerow(('BCDEMO-DAILY', store.code, product.sku,
            b.astimezone(TAIPEI).date().isoformat(), 20, '0', '1'))
    payload = dict(store_id=store.id, import_mode='daily_posting', csv_text=daily.getvalue())
    validation = sales.validate(payload=payload, actor_id=actor.id, session=session)
    if not validation['valid']:
        raise DomainError('CSV_INVALID', '合成日常入帳驗證失敗', details=validation['errors'])
    sales.commit(payload=payload, actor_id=actor.id, validation_token=validation['validation_token'], session=session)
    inventory = get_provider('inventory_writer')
    for stock in stocks:
        inventory.submit_count(store_id=store.id, product_id=stock.product_id, actor_id=actor.id,
            cutoff_at=b, physical_qty=20, unsellable_qty=0, expected_version=stock.version,
            request_key=f'BCDEMO-count-{stock.product_id}', reason='合成示範：21:00核對可售20件', session=session)
    run = ReplenishmentService().generate(store_id=store.id, actor_id=actor.id, cycle_id=cycle.id,
        expected_version=store.calculation_version, session=session)
    session.flush()
    source = '受控 D 未結來源' if current_app.extensions['service_providers']['open_orders'][1] else '正式 D 未結來源'
    return (f'新增 BCDEMO（門市id={store.id}），正式 B 快照#{run.run_id}，{source}；非完整閉環驗收。'
        f' 帳號 bcmanager，密碼取自本機 DEMO_PASSWORD；/store/ordering?store_id={store.id}。'
        ' 合成七日平均20、H20、L1、SS10；無未結量時飲料建議30。既有資料、帳號與時鐘未修改。')
