"""B05 demo numerical walkthrough. All service writes are rolled back."""
import sys
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.contracts import dto_dict
from app.extensions import db
from app.models import Store, User, Inventory, InventoryMovement, InventoryReconciliation, SalesDaily, BusinessClock, DeliveryCycle
from app.services.clock import business_now, round_window
from app.services.inventory_operations import InventoryOperations
from app.services.manual_forecasting import ManualForecastService
from app.providers import get_provider

app=create_app()
with app.app_context():
    assert app.config['APP_ENV']=='demo' and app.config['MODULE_DEV']=='B'
    assert (db.engine.url.database or '').startswith('system2_b') and db.engine.url.database.endswith('_demo')
    def protected_state():
        db.session.expire_all()
        return (
            [db.session.scalar(db.select(db.func.count()).select_from(t)) for t in db.metadata.tables.values()],
            [(s.id,s.calculation_version) for s in db.session.execute(db.select(Store).order_by(Store.id)).scalars()],
            [(s.id,s.book_physical_qty,s.book_unsellable_qty,s.version,s.counted_at,s.reconciliation_required)
                for s in db.session.execute(db.select(Inventory).order_by(Inventory.id)).scalars()],
            [(s.id,s.sold_qty,s.version) for s in db.session.execute(db.select(SalesDaily).order_by(SalesDaily.id)).scalars()],
            db.session.get(BusinessClock,1).business_anchor)
    before=protected_state();db.session.rollback()
    try:
        store=db.session.execute(db.select(Store).where(Store.code=='B05DEMO')).scalar_one()
        actor=db.session.execute(db.select(User).where(User.username=='b05manager')).scalar_one()
        stocks=db.session.execute(db.select(Inventory).where(Inventory.store_id==store.id)
            .order_by(Inventory.product_id)).scalars().all()
        now=business_now();b=round_window(now)[0]
        assert (stocks[0].book_physical_qty,stocks[0].book_unsellable_qty)==(32,2),'案例已變更，請保留資料；不要重設。'
        original=db.session.execute(db.select(InventoryMovement).where(InventoryMovement.store_id==store.id,
            InventoryMovement.source_id=='B05-SYNTHETIC-RECEIPT-SKU01')).scalar_one()
        body=dict(store_id=store.id,product_id=stocks[0].product_id,actor_id=actor.id,kind='disposal',qty=2,
            expected_version=stocks[0].version,source_id='B05-ROLLBACK-NUMERIC',occurred_at=now,
            reason='合成數字核對，整筆回滾',session=db.session)
        service=InventoryOperations();removed=service.remove_damaged(**body)
        assert (removed.physical_book,removed.unsellable_book)==(30,0)
        assert service.remove_damaged(**body).replayed
        assert (original.physical_delta,original.unsellable_delta)==(12,2)
        print('PASS damaged removal: 32/2/H30 -> 30/0/H30, original receipt preserved, retry does not deduct again.')
        tasks=db.session.execute(db.select(InventoryReconciliation).where(
            InventoryReconciliation.store_id==store.id,InventoryReconciliation.status=='OPEN')).scalars().all()
        for task in tasks:
            negative=task.source_type=='negative_book'
            row=next(s for s in stocks if s.product_id==task.product_id)
            count=dict(store_id=store.id,product_id=row.product_id,actor_id=actor.id,cutoff_at=b,
                physical_qty=10 if negative else 20,unsellable_qty=0,expected_version=row.version,
                request_key='B05-ROLLBACK-COUNT-'+str(task.id),reason='核對有效21:00盤點，合成數字整筆回滾',
                correction=not negative,expected_count_version=None if negative else 1,session=db.session)
            result=service.resolve_with_count(task_id=task.id,expected_task_version=task.version,**count)
            assert task.status=='RESOLVED'
            assert result.physical_delta==(15 if negative else 0)
            assert row.book_physical_qty==(10 if negative else 30)
        assert len(tasks)==2
        print('PASS reconciliation: negative -5 -> count10/delta15/H10; covered count20/delta0 keeps post-cutoff receipt10/book30.')
        writer=get_provider('runs')
        cycle=db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==store.id)
            .order_by(DeliveryCycle.arrival_at)).scalars().first()
        def generate(**extra):
            return writer.generate(store_id=store.id,actor_id=actor.id,cycle_id=cycle.id,
                expected_version=store.calculation_version,session=db.session,**extra)
        model=generate()
        assert [i.suggested_qty for i in model.items]==[24,42,15,None]
        pid=stocks[3].product_id
        ManualForecastService().save(store_id=store.id,product_id=pid,actor_id=actor.id,
            daily_demand='5.125',reason='合成有效人工日需求，整筆回滾',expected_version=store.calculation_version,session=db.session)
        manual=generate(modes={pid:'manual'},manual_confirmations=(pid,))
        assert manual.items[3].mu==Decimal('5.125') and manual.items[3].suggested_qty==13
        direct=generate(modes={pid:'direct'},direct_quantities={pid:1000},
            special_needs={pid:dict(need_date=cycle.arrival_at.date().isoformat(),need_qty=1000,
                reason='社區活動一千件，具體數量已核對',arrangement='到貨直接交付活動單位')})
        item=direct.items[3]
        assert item.mu is None and item.suggested_qty is None and not item.timeline_committed
        bound=next(w.details['conservative_capacity'] for w in item.warnings if w.code=='DIRECT_ORDER')
        assert bound['upper_bound_with_pending']==1008
        assert not item.input_snapshot['forecast_quality']['valid']
        print('PASS real B runs: model Q24/42/15/null, manual5.125/Q13, direct1000/null/no curves/conservative1008.')
        from app.services.sales import SalesService
        csv=Path('demo/b05_historical_sample.csv').read_text(encoding='utf-8')
        data=dict(store_id=store.id,csv_text=csv,import_mode='historical')
        sales=SalesService()
        invalid=sales.validate(payload={**data,'csv_text':Path('demo/b05_invalid_sample.csv').read_text(encoding='utf-8')},
            actor_id=actor.id,session=db.session)
        assert not invalid['valid'] and any(e['code']=='UNKNOWN_PRODUCT' for e in invalid['errors'])
        preview=sales.validate(payload=data,actor_id=actor.id,session=db.session)
        assert preview['valid'], preview['errors']
        result=sales.commit(payload=data,actor_id=actor.id,validation_token=preview['validation_token'],session=db.session)
        assert result['stock_delta']==0 and stocks[3].book_physical_qty==8
        assert sales.commit(payload=data,actor_id=actor.id,validation_token=preview['validation_token'],session=db.session)['replayed']
        complete=generate()
        assert complete.items[3].suggested_qty==42
        print('PASS CSV: invalid batch refused; historical missing day added with stock delta0/H8; same request replayed; complete model SKU04 Q42.')
    finally:
        db.session.rollback()
    assert protected_state()==before
    print('PASS all table counts, store/stock/sales versions and business clock unchanged after rollback.')
