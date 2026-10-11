"""B05 additive, isolated synthetic walkthrough using the real B writers."""
import os
from datetime import time, timedelta
import click
from flask import current_app
from app.extensions import db
from app.models import Store, User, Product, PolicyVersion, StoreProduct, DeliveryCycle, Inventory, SalesDaily, SalesImportBatch, InventoryReconciliation
from app.contracts import InventoryMutation
from app.services.clock import round_window, utc_naive
from app.services.inventory import InventoryService, _business_now, _audit, _reconciliation_context, _lock_store, _inventory
from app.services.sales import SalesService
from app.services.version import transaction

def register_operations_demo(bp):
    @bp.cli.command('prepare-b05-demo')
    def prepare():
        if current_app.config['APP_ENV']!='demo' or current_app.config['MODULE_DEV']!='B':
            raise click.ClickException('僅限 APP_ENV=demo、MODULE_DEV=B')
        name=db.engine.engine.url.database or ''
        if not name.startswith('system2_b') or not name.endswith('_demo'):
            raise click.ClickException('僅允許 B 自己的 system2_b*_demo')
        with transaction():
            existing=db.session.execute(db.select(Store.id).where(Store.code=='B05DEMO')).scalar_one_or_none()
            if existing:
                # Add missing deadline metadata only for this command's identified synthetic store.
                marker=db.session.execute(db.select(SalesImportBatch.id).where(
                    SalesImportBatch.store_id==existing,SalesImportBatch.source_batch_id=='B05-SYNTHETIC-HISTORY')).first()
                if marker:
                    target=_lock_store(db.session,existing)
                    ids=db.session.scalars(db.select(Inventory.product_id).where(Inventory.store_id==existing).order_by(Inventory.product_id)).all()
                    for pid in ids:_inventory(db.session,existing,pid,lock=True)
                    tasks=db.session.scalars(db.select(InventoryReconciliation).where(
                        InventoryReconciliation.store_id==existing).order_by(InventoryReconciliation.id).with_for_update()).all()
                    changed=[]
                    for task in tasks:
                        if not (task.resolution or {}).get('due_at'):
                            from app.services.clock import aware
                            task.resolution={**_reconciliation_context(db.session,existing,task.product_id,aware(task.created_at)),
                                             **(task.resolution or {})}
                            task.version+=1;changed.append(task.id)
                    if changed:
                        from app.services.version import bump_store
                        bump_store(target)
                        owner=db.session.execute(db.select(User).where(User.username=='b05manager')).scalar_one()
                        _audit(db.session,owner.id,existing,'inventory.demo_deadlines_backfilled',f'store:{existing}',{},
                            {'synthetic':True,'reconciliation_ids':changed},_business_now(db.session))
                        click.echo('只補存 B05 合成案件期限／版本；庫存、銷售、密碼與時鐘保持原值。')
                click.echo('B05DEMO 已存在，保留原資料／密碼／時鐘；畫面 /store/data，帳號 b05manager。')
                return
            if db.session.execute(db.select(User.id).where(User.username=='b05manager')).first():
                raise click.ClickException('帳號已存在，拒絕覆寫')
            password=os.environ.get('DEMO_PASSWORD','')
            if len(password)<8 or password.startswith('REPLACE_'):
                raise click.ClickException('請先設定本機 DEMO_PASSWORD')
            now=_business_now(db.session);b,cutoff=round_window(now)
            if not b<=now<cutoff or now<b+timedelta(minutes=10):
                raise click.ClickException('B05合成案例需本輪21:10–22:00；不自動變更時鐘')
            products=db.session.execute(db.select(Product).where(Product.sku.in_(('SKU01','SKU02','SKU03','SKU04')))
                .order_by(Product.sku)).scalars().all()
            if len(products)!=4:
                raise click.ClickException('缺少 SKU01–04；未覆寫商品主檔')
            store=Store(code='B05DEMO',name='B05合成完整模組驗收',cutoff=time(22))
            db.session.add(store);db.session.flush()
            actor=User(username='b05manager',role='manager',stores=[store]);actor.set_password(password)
            db.session.add(actor);db.session.flush()
            batch=SalesImportBatch(store_id=store.id,source_batch_id='B05-SYNTHETIC-HISTORY',payload_hash='d'*64,
                import_mode='historical',actor_id=actor.id,created_at=utc_naive(now),
                snapshot={'synthetic':True,'baseline_checked':True,'stock_effect':0})
            db.session.add(batch);db.session.flush()
            from app.seed import POLICY
            stocks={}
            for index,p in enumerate(products):
                policy=PolicyVersion(store_id=store.id,product_id=p.id,version=1,effective_at=utc_naive(b),
                    parameters={**POLICY,'lead_days':1,'safety_stock':10,'capacity':100,'pack_size':p.pack_size})
                db.session.add(policy);db.session.flush()
                db.session.add(StoreProduct(store_id=store.id,product_id=p.id,policy_version_id=policy.id,
                    lead_days=1,safety_stock=10,capacity=100))
                h=8 if index==3 else 20
                row=Inventory(store_id=store.id,product_id=p.id,physical_qty=h,unsellable_qty=0,
                    book_physical_qty=h,book_unsellable_qty=0,counted_at=utc_naive(b-timedelta(days=1) if index in (1,2) else b),
                    updated_at=utc_naive(now))
                db.session.add(row);stocks[p.sku]=row
                for days in range(6,-1,-1):
                    if index in (1,2) and days==0 or index==3 and days==6:continue
                    end=b-timedelta(days=days)
                    db.session.add(SalesDaily(store_id=store.id,product_id=p.id,business_date=end.date(),
                        interval_start=utc_naive(end-timedelta(days=1)),interval_end=utc_naive(end),
                        sold_qty=20,was_stockout=False,is_open=True,batch_id=batch.id,import_mode='historical'))
            for lead in (1,2,3):
                db.session.add(DeliveryCycle(store_id=store.id,baseline_at=utc_naive(b),cutoff_at=utc_naive(cutoff),
                    arrival_at=utc_naive(b+timedelta(days=lead))))
            db.session.flush()
            inventory=InventoryService();sales=SalesService()
            def post(sku,qty,key,target=None):
                csv='source_batch_id,store_code,sku,business_date,sold_qty,was_stockout,is_open\n'
                csv+=f'{key},{store.code},{sku},{b.date().isoformat()},{qty},0,1\n'
                payload=dict(store_id=store.id,csv_text=csv,import_mode='daily_posting',
                    replaces_batch_id=target,reason='B05合成日常／盤點後更正' if target else '')
                preview=sales.validate(payload=payload,actor_id=actor.id,session=db.session)
                if not preview['valid']:
                    raise click.ClickException('合成資料驗證失敗；整筆回滾：'+str(preview['errors']))
                return sales.commit(payload=payload,actor_id=actor.id,validation_token=preview['validation_token'],session=db.session)
            post('SKU02',25,'B05-SYNTHETIC-NEGATIVE')
            noodle=post('SKU03',0,'B05-SYNTHETIC-DAILY')
            row=stocks['SKU03']
            inventory.submit_count(store_id=store.id,product_id=row.product_id,actor_id=actor.id,cutoff_at=b,
                physical_qty=20,unsellable_qty=0,expected_version=row.version,
                request_key='B05-SYNTHETIC-NOODLE-COUNT',reason='合成有效21:00盤點',session=db.session)
            for sku,qty,damaged in [('SKU01',12,2),('SKU03',10,0)]:
                row=stocks[sku]
                inventory.apply_movement(mutation=InventoryMutation(store.id,row.product_id,'receipt',
                    'B05-SYNTHETIC-RECEIPT-'+sku,qty,damaged,row.version,actor.id,
                    b+timedelta(minutes=10),'合成收貨來源，D真實履約待A05'),session=db.session)
            post('SKU03',1,'B05-SYNTHETIC-COVERED',noodle['batch_id'])
            _audit(db.session,actor.id,store.id,'inventory.b05_demo_prepared',f'store:{store.id}',{},
                {'synthetic':True,'baseline_at':b.isoformat(),'d_fulfillment':False},now)
            db.session.flush()
            click.echo(f'新增 B05DEMO（id={store.id}）／b05manager；密碼沿用本機 DEMO_PASSWORD。')
            click.echo('飲料32/不可售2/H30；雨衣帳面-5待有效盤點；泡麵30且盤點涵蓋更正待對帳；衛生紙H8、缺一日。')
            click.echo('保留其他門市、時鐘與憑證。收貨為合成B來源，未宣稱D真實整合。')
