"""Additive B03 synthetic store; never overwrites existing demonstration activity."""
import os
from datetime import time, timedelta
import click
from flask import current_app
from app.extensions import db
from app.models import Store, User, Product, PolicyVersion, StoreProduct, DeliveryCycle, Inventory, SalesDaily, SalesImportBatch
from app.services.clock import round_window, utc_naive
from app.services.inventory import _business_now, _audit
from app.services.version import transaction

def register_replenishment_demo(bp):
    @bp.cli.command('prepare-b03-demo')
    def prepare_b03_demo():
        if current_app.config['APP_ENV'] != 'demo' or current_app.config['MODULE_DEV'] != 'B':
            raise click.ClickException('僅限 APP_ENV=demo、MODULE_DEV=B')
        name = db.engine.engine.url.database or ''
        if not name.startswith('system2_b') or not name.endswith('_demo'):
            raise click.ClickException('僅允許 B 自己的 system2_b*_demo')
        with transaction():
            existing = db.session.execute(db.select(Store).where(Store.code == 'B03DEMO')).scalar_one_or_none()
            if existing is not None:
                click.echo('B03DEMO 已存在，保留所有資料；未重設、未更改密碼或時鐘。')
                click.echo('帳號 b03manager；畫面 /store/replenishment。')
                return
            if db.session.execute(db.select(User.id).where(User.username == 'b03manager')).first():
                raise click.ClickException('帳號名稱已存在，拒絕覆寫')
            password = os.environ.get('DEMO_PASSWORD', '')
            if len(password) < 8 or password.startswith('REPLACE_'):
                raise click.ClickException('請先設定本機 DEMO_PASSWORD，未修改任何帳號')
            now = _business_now(db.session)
            b, cutoff = round_window(now)
            if not b <= now < cutoff:
                raise click.ClickException('本機業務時間須為21:00–22:00；不自動調整或倒退時鐘')
            products = db.session.execute(db.select(Product).where(Product.sku.in_(('SKU01','SKU02','SKU03')))
                .order_by(Product.sku)).scalars().all()
            if len(products) != 3:
                raise click.ClickException('缺少既有 SKU01–03；未改寫商品主檔')
            store = Store(code='B03DEMO', name='B03合成計算核對門市', cutoff=time(22))
            db.session.add(store); db.session.flush()
            actor = User(username='b03manager', role='manager', stores=[store])
            actor.set_password(password); db.session.add(actor); db.session.flush()
            from app.seed import POLICY
            batch = SalesImportBatch(store_id=store.id, source_batch_id='B03-SYNTHETIC-7D', payload_hash='b'*64,
                import_mode='historical', actor_id=actor.id, created_at=utc_naive(now),
                snapshot={'synthetic':True,'baseline_checked':True,'stock_effect':0,'purpose':'B03 calculation only'})
            db.session.add(batch); db.session.flush()
            for index, product in enumerate(products):
                params = {**POLICY,'lead_days':1,'safety_stock':10,'capacity':100,'pack_size':product.pack_size}
                policy = PolicyVersion(store_id=store.id, product_id=product.id, version=1,
                    effective_at=utc_naive(b), parameters=params)
                db.session.add(policy); db.session.flush()
                db.session.add(StoreProduct(store_id=store.id, product_id=product.id, policy_version_id=policy.id,
                    lead_days=1,safety_stock=10,capacity=100))
                h = 60 if index==1 else 8
                db.session.add(Inventory(store_id=store.id, product_id=product.id, physical_qty=h,
                    unsellable_qty=0,book_physical_qty=h,book_unsellable_qty=0,
                    counted_at=utc_naive(b),updated_at=utc_naive(now)))
                values = [18,22,20,19,21,20,20] if index==0 else [0]*7 if index==1 else [20]*7
                for days,value in zip(range(6,-1,-1),values):
                    if index==2 and days==6: continue  # Deliberate missing day, never zero-filled.
                    end=b-timedelta(days=days)
                    db.session.add(SalesDaily(store_id=store.id,product_id=product.id,business_date=end.date(),
                        interval_start=utc_naive(end-timedelta(days=1)),interval_end=utc_naive(end),
                        sold_qty=value,was_stockout=False,is_open=True,batch_id=batch.id,import_mode='historical'))
            for lead in (1,2,3):
                db.session.add(DeliveryCycle(store_id=store.id,baseline_at=utc_naive(b),cutoff_at=utc_naive(cutoff),
                    arrival_at=utc_naive(b+timedelta(days=lead))))
            _audit(db.session,actor.id,store.id,'replenishment.demo_prepared',f'store:{store.id}',{},
                {'synthetic':True,'baseline_at':b.isoformat()},now)
            db.session.flush()
            click.echo(f'新增 B03DEMO（門市id={store.id}），基準 {b.isoformat()}；既有DEMO1／DEMO2、時鐘及憑證保持原值。')
        click.echo('帳號 b03manager；密碼沿用本機 DEMO_PASSWORD。畫面 /store/replenishment。')
        click.echo('合成庫存／歷史資料：飲料 H8、七日平均20、L1建議42；雨衣 H60、零銷售、建議0；泡麵缺一日、建議null。')
