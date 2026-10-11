"""B03 real calculations in isolated MySQL; D inputs remain controlled."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
import pytest
from app.contracts import OpenOrdersDTO, OpenSourceDTO, dto_dict
from app.extensions import db
from app.models import Store, User, Inventory, SalesDaily, BusinessClock, DeliveryCycle, StoreProduct, PolicyVersion, ReplenishmentRun, RunItem, AuditEvent
from app.providers import get_provider, register_provider
from app.services.clock import business_now, utc_naive
from app.services.errors import DomainError
from app.services.forecasting import calculate
from app.services.replenishment import ReplenishmentService
from app.testing.providers import ControlledOpenOrders
from conftest import login

@pytest.fixture
def case(seeded):
    store = db.session.execute(db.select(Store).where(Store.code=='DEMO1')).scalar_one()
    actor = db.session.execute(db.select(User).where(User.username=='manager1')).scalar_one()
    b = business_now()
    db.session.get(BusinessClock,1).business_anchor = utc_naive(b+timedelta(minutes=20))
    stocks = db.session.execute(db.select(Inventory).where(Inventory.store_id==store.id).order_by(Inventory.product_id)).scalars().all()
    stocks[0].physical_qty = stocks[0].book_physical_qty = 8
    rows = db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id==store.id,
        SalesDaily.product_id==stocks[0].product_id, SalesDaily.business_date.between((b-timedelta(days=6)).date(),b.date()))
        .order_by(SalesDaily.business_date)).scalars().all()
    for row,value in zip(rows,[18,22,20,19,21,20,20]):
        row.sold_qty=value
    cycles = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==store.id).order_by(DeliveryCycle.arrival_at)).scalars().all()
    register_provider('open_orders',ControlledOpenOrders(),test_only=True)
    db.session.flush()
    return dict(store=store,actor=actor,b=b,stocks=stocks,rows=rows,cycles=cycles,service=ReplenishmentService())

def generate(c,cycle=0):
    return c['service'].generate(store_id=c['store'].id,actor_id=c['actor'].id,cycle_id=c['cycles'][cycle].id,
        expected_version=c['store'].calculation_version,session=db.session)

def evaluate(c,run,cycle=0,final=None,now=None):
    return c['service'].evaluate(run_id=run.run_id,store_id=run.store_id,actor_id=c['actor'].id,
        cycle_id=c['cycles'][cycle].id,final_quantities=final or {},manual_confirmations=(),
        evaluated_at=now or c['b']+timedelta(minutes=20),session=db.session)

def codes(item):
    return {w.code for w in item.warnings}

def policy(c,**changes):
    sp=db.session.execute(db.select(StoreProduct).where(StoreProduct.store_id==c['store'].id,StoreProduct.product_id==c['stocks'][0].product_id)).scalar_one()
    old=db.session.get(PolicyVersion,sp.policy_version_id)
    new=PolicyVersion(store_id=old.store_id,product_id=old.product_id,version=old.version+1,
        effective_at=utc_naive(c['b']),parameters={**old.parameters,**changes})
    db.session.add(new); db.session.flush(); sp.policy_version_id=new.id
    for k in ('safety_stock','capacity','lead_days'):
        if k in changes: setattr(sp,k,changes[k])
    db.session.flush()

@pytest.mark.parametrize('h,qty,expected',[(8,12,30),(9,12,30),(60,0,0),(8,0,42)])
def test_formula(h,qty,expected):
    source=type('Source',(),{'quantity':qty,'bucket':'C'})()
    mu,target,raw,q=calculate(140,lead_days=1,safety_stock=10,h=h,sources=(source,),pack_size=6)
    assert (mu,target,q)==(20,50,expected) and raw==max(0,50-h-qty)

@pytest.mark.parametrize('total,lead,pack',[(21,1,6),(7,5,6),(1,6,1),(49,1,7),(7,1,1)])
def test_exact_box_boundary(total,lead,pack):
    mu,target,raw,q=calculate(total,lead_days=lead,safety_stock=0,h=0,sources=(),pack_size=pack)
    assert Fraction(q)==raw

def test_real_numeric_snapshot(case):
    register_provider('open_orders',ControlledOpenOrders('committed'),test_only=True)
    run=generate(case); item=run.items[0]
    assert isinstance(get_provider('runs'),ReplenishmentService)
    assert (item.h,item.mu,item.target_stock,item.raw_qty,item.suggested_qty)==(8,Decimal(20),Decimal(50),Decimal(30),30)
    assert item.run_item_id and run.baseline_at==case['b'] and run.actual_generated_at==case['b']+timedelta(minutes=20)
    assert run.data_through_at==case['b'] and run.protection_end==case['b']+timedelta(days=2)
    assert len(item.input_snapshot['sales'])==7 and item.input_snapshot['source_provider']['test_only']
    first=item.timeline_committed[1]
    assert (first['demand'],first['stockout_qty'],first['ending_stock'])==('20','12','42')
    assert {r['source_id'] for r in first['receipts']}=={'candidate','controlled-1'}
    assert 'PRE_ARRIVAL_STOCKOUT' in codes(item) and case['store'].calculation_version==1
    assert case['stocks'][0].book_physical_qty==8
    read=case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session)
    assert dto_dict(read)==dto_dict(run)

@pytest.mark.parametrize('scenario,q,bucket',[('normal',42,None),('pending',30,'U'),('committed',30,'C'),('late',42,'RISK'),('disputed',42,'RISK'),('expired',42,'RISK')])
def test_sources(case,scenario,q,bucket):
    register_provider('open_orders',ControlledOpenOrders(scenario),test_only=True)
    item=generate(case).items[0]
    assert item.suggested_qty==q and (item.sources[0].bucket if item.sources else None)==bucket
    if bucket=='RISK': assert 'LOGISTICS_RISK' in codes(item)
    if bucket=='U':
        assert 'PENDING_SUPPLY' in codes(item)
        assert item.timeline_committed[1]['ending_stock']=='30' and item.timeline_with_pending[1]['ending_stock']=='42'

@pytest.mark.parametrize('problem',['missing','closed','stockout','interval'])
def test_quality_not_zero(case,problem):
    row=case['rows'][0]
    if problem=='missing': db.session.delete(row)
    elif problem=='closed': row.is_open=False
    elif problem=='stockout': row.was_stockout=True
    else: row.interval_start+=timedelta(hours=1)
    db.session.flush(); item=generate(case).items[0]
    assert item.mode=='unavailable' and item.h==8 and 'FORECAST_INSUFFICIENT' in codes(item)
    assert all(v is None for v in (item.mu,item.target_stock,item.raw_qty,item.suggested_qty))
    assert not item.timeline_committed and len(item.input_snapshot['sales'])==7

def test_zero_and_decimal_readback(case):
    for row in case['rows']: row.sold_qty=0
    db.session.flush(); item=generate(case).items[0]
    assert (item.mu,item.target_stock,item.raw_qty,item.suggested_qty)==(0,10,2,6) and 'ZERO_SALES' in codes(item)
    case['stocks'][0].book_physical_qty=60; db.session.flush()
    assert generate(case).items[0].suggested_qty==0
    case['rows'][0].sold_qty=1; db.session.flush()
    run=generate(case); db.session.expire_all()
    read=case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session)
    assert read.items[0].mu==run.items[0].mu and str(read.items[0].mu).startswith('0.142857142857142857142857')

@pytest.mark.parametrize('problem',['gap','negative','reconciliation'])
def test_inventory_not_zero(case,problem):
    row=case['stocks'][0]
    if problem=='gap': row.counted_at-=timedelta(days=1)
    elif problem=='negative': row.book_physical_qty=-1
    else: row.reconciliation_required=True
    db.session.flush(); item=generate(case).items[0]
    assert item.h is None and item.suggested_qty is None and codes(item)&{'INVENTORY_GAP','NEGATIVE_BOOK'}

def test_cycle_final_risks_do_not_mutate(case):
    run=generate(case); result=evaluate(case,run,cycle=2,final={run.items[0].product_id:1000}); item=result.items[0]
    assert item.lead_days==3 and item.target_stock==90 and item.suggested_qty==84
    assert result.baseline_at==run.baseline_at and result.actual_generated_at==run.actual_generated_at
    assert {'CAPACITY','LARGE_QUANTITY','DEVIATION','PRE_ARRIVAL_STOCKOUT'}<=codes(item)
    assert any(r['qty']==1000 for p in item.timeline_committed for r in p['receipts'])
    original=case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session)
    assert original.items[0].suggested_qty==42 and original.cycle_id==run.cycle_id

def test_capacity_at_arrival_and_pending_curve(case):
    case['stocks'][0].book_physical_qty=60; db.session.flush()
    run=generate(case)
    assert 'CAPACITY' not in codes(evaluate(case,run,final={run.items[0].product_id:60}).items[0])
    assert 'CAPACITY' in codes(evaluate(case,run,final={run.items[0].product_id:66}).items[0])
    case['stocks'][0].book_physical_qty=8; policy(case,capacity=35)
    register_provider('open_orders',ControlledOpenOrders('pending'),test_only=True)
    item=generate(case).items[0]
    assert not item.timeline_committed[1]['capacity_exceeded'] and item.timeline_with_pending[1]['capacity_exceeded']
    register_provider('open_orders',ControlledOpenOrders('late'),test_only=True)
    item=generate(case).items[0]
    assert item.timeline_committed[-1]['at']==item.sources[0].eta.isoformat()

def test_expiry_without_version_change(case):
    class Expiring:
        def get_open_orders(self,**kw):
            now=kw['evaluated_at']; expiry=case['b']+timedelta(minutes=30)
            source=OpenSourceDTO('pending','expiry',case['stocks'][0].product_id,12,'U' if now<expiry else 'RISK',
                case['b']+timedelta(days=1),expiry,False)
            return OpenOrdersDTO(kw['store_id'],case['store'].calculation_version,kw['baseline_at'],kw['protection_end'],now,(source,))
    register_provider('open_orders',Expiring(),test_only=True); run=generate(case)
    expired=evaluate(case,run,now=case['b']+timedelta(minutes=30))
    assert run.items[0].suggested_qty==30 and expired.items[0].suggested_qty==42
    assert expired.store_version==run.store_version and 'LOGISTICS_RISK' in codes(expired.items[0])

@pytest.mark.parametrize('problem',['version','store','time','product','duplicate','bucket'])
def test_provider_validation(case,problem):
    class Bad:
        def get_open_orders(self,**kw):
            value=ControlledOpenOrders('committed').get_open_orders(**kw)
            if problem=='version': return replace(value,store_version=99)
            if problem=='store': return replace(value,store_id=999)
            if problem=='time': return replace(value,evaluated_at=kw['evaluated_at']+timedelta(seconds=1))
            if problem=='product': return replace(value,sources=(replace(value.sources[0],product_id=99999),))
            if problem=='duplicate': object.__setattr__(value,'sources',value.sources+value.sources)
            if problem=='bucket': object.__setattr__(value.sources[0],'source_type','pending')
            return value
    register_provider('open_orders',Bad(),test_only=True)
    with pytest.raises(DomainError): generate(case)
    assert db.session.execute(db.select(db.func.count(ReplenishmentRun.id))).scalar_one()==0

def test_overflow_not_truncated(case):
    for row in case['rows']: row.sold_qty=1_000_000
    db.session.flush(); item=generate(case).items[0]
    assert item.mode=='unavailable' and item.mu is None and item.suggested_qty is None and 'INVALID_QUANTITY' in codes(item)

def test_rollback_and_immutable_records(case):
    before=db.session.execute(db.select(db.func.count(AuditEvent.id))).scalar_one()
    nested=db.session.begin_nested(); run=generate(case); nested.rollback()
    assert db.session.execute(db.select(db.func.count(ReplenishmentRun.id))).scalar_one()==0
    assert db.session.execute(db.select(db.func.count(AuditEvent.id))).scalar_one()==before
    run=generate(case)
    for cls,ident,field,value in [(ReplenishmentRun,run.run_id,'store_version',99),(RunItem,run.items[0].run_item_id,'suggested_qty',0)]:
        nested=db.session.begin_nested(); setattr(db.session.get(cls,ident),field,value)
        with pytest.raises(DomainError) as error: db.session.flush()
        assert error.value.code=='IMMUTABLE_RECORD'; nested.rollback()

@pytest.mark.parametrize('minute',[-1,60,61])
def test_closed_window_preserves_history(case,minute):
    run=generate(case); db.session.get(BusinessClock,1).business_anchor=utc_naive(case['b']+timedelta(minutes=minute)); db.session.flush()
    with pytest.raises(DomainError) as error: generate(case)
    assert error.value.code=='CUTOFF_PASSED'
    assert case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session).run_id==run.run_id
    with pytest.raises(DomainError): evaluate(case,run)

def test_stale_role_and_final_validation(case):
    run=generate(case); case['store'].calculation_version+=1; db.session.flush()
    with pytest.raises(DomainError) as error: evaluate(case,run)
    assert error.value.code=='VERSION_CONFLICT'
    run=generate(case)
    for name,status in [('manager2',404),('operator',403)]:
        actor=db.session.execute(db.select(User).where(User.username==name)).scalar_one()
        with pytest.raises(DomainError) as error:
            case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=actor.id,session=db.session)
        assert error.value.status==status
    for value in [True,1.5,-1,1_000_001]:
        with pytest.raises(DomainError): evaluate(case,run,final={run.items[0].product_id:value})
    odd=evaluate(case,run,final={run.items[0].product_id:31}).items[0]
    assert 'INVALID_PACK' in codes(odd) and any(r['qty']==31 for p in odd.timeline_committed for r in p['receipts'])

def test_api_permissions_csrf_history(case,client):
    assert login(client).status_code==200
    assert client.get('/store/replenishment').status_code==200
    assert client.get('/api/replenishment/context').json['source_provider']['test_only']
    body=dict(store_id=case['store'].id,cycle_id=case['cycles'][0].id,expected_version=1)
    assert client.post('/api/replenishment/runs',json=body).status_code==400
    token=client.get('/api/auth/csrf').json['csrf_token']
    response=client.post('/api/replenishment/runs',json=body,headers={'X-CSRFToken':token})
    assert response.status_code==201, response.json
    result=response.json; url='/api/replenishment/runs/'+str(result['run_id'])
    assert result['items'][0]['mu']=='20' and client.get(url).json==result
    response=client.post(url+'/evaluate',json={'store_id':body['store_id'],'cycle_id':body['cycle_id'],
        'final_quantities':{str(result['items'][0]['product_id']):31}},headers={'X-CSRFToken':token})
    assert response.status_code==200 and 'INVALID_PACK' in {w['code'] for w in response.json['items'][0]['warnings']}
    assert client.get(url).json==result
    login(client,'manager2')
    assert client.get(url+'?store_id='+str(body['store_id'])).status_code==404
    login(client,'operator'); assert client.get('/store/replenishment').status_code==403
    login(client,'admin'); assert client.get(url+'?store_id='+str(body['store_id'])).status_code==200

def test_missing_provider_fails_closed(case):
    from flask import current_app
    del current_app.extensions['service_providers']['open_orders']
    with pytest.raises(DomainError) as error: generate(case)
    assert error.value.code=='SERVICE_UNAVAILABLE'

def test_overdue_source_not_backdated(case):
    class Overdue:
        def get_open_orders(self,**kw):
            source=OpenSourceDTO('shipment','old',case['stocks'][0].product_id,50,'RISK',
                case['b']-timedelta(days=1),None,False)
            return OpenOrdersDTO(kw['store_id'],case['store'].calculation_version,kw['baseline_at'],kw['protection_end'],kw['evaluated_at'],(source,))
    register_provider('open_orders',Overdue(),test_only=True); item=generate(case).items[0]
    assert item.suggested_qty==42 and 'LOGISTICS_RISK' in codes(item)
    assert not any(r['source_id']=='old' for p in item.timeline_with_pending for r in p['receipts'])

def test_provider_construction_error_is_domain_error(case):
    class Duplicate:
        def get_open_orders(self,**kw):
            source=OpenSourceDTO('committed','dup',case['stocks'][0].product_id,12,'C',
                case['b']+timedelta(days=1),None,False)
            return OpenOrdersDTO(kw['store_id'],case['store'].calculation_version,kw['baseline_at'],kw['protection_end'],kw['evaluated_at'],(source,source))
    register_provider('open_orders',Duplicate(),test_only=True)
    with pytest.raises(DomainError) as error: generate(case)
    assert error.value.code=='PROVIDER_MISMATCH' and error.value.status==409

def test_invalid_cycle_and_manual_confirmation_are_rejected(case):
    run=generate(case)
    other=db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id!=run.store_id)).scalars().first()
    with pytest.raises(DomainError):
        case['service'].evaluate(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,
            cycle_id=other.id,final_quantities={},manual_confirmations=(),
            evaluated_at=case['b']+timedelta(minutes=20),session=db.session)
    with pytest.raises(DomainError) as error:
        case['service'].evaluate(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,
            cycle_id=run.cycle_id,final_quantities={},manual_confirmations=(run.items[0].product_id,),
            evaluated_at=case['b']+timedelta(minutes=20),session=db.session)
    assert error.value.code=='UNSUPPORTED_MODE'

def test_v31_2140_still_l1(case):
    db.session.get(BusinessClock,1).business_anchor=utc_naive(case['b']+timedelta(minutes=40))
    db.session.flush(); run=generate(case)
    assert run.baseline_at==case['b'] and run.items[0].lead_days==1
    assert run.actual_generated_at==case['b']+timedelta(minutes=40)
    assert run.protection_end==case['b']+timedelta(days=2)

def test_real_run_consumed_by_existing_c_draft(case,client):
    # Minimal read/create compatibility proof. Formal cross-module acceptance remains A05.
    run=generate(case); db.session.commit(); login(client)
    assert client.get('/store/ordering').status_code==200
    token=client.get('/api/auth/csrf').json['csrf_token']
    assert client.post('/api/ordering/acknowledgement',json={'acknowledged':True},headers={'X-CSRFToken':token}).status_code==200
    response=client.post('/api/order-drafts',json={'store_id':run.store_id,'run_id':run.run_id,'cycle_id':run.cycle_id},
        headers={'X-CSRFToken':token})
    assert response.status_code==201, response.json
    assert response.json['run_id']==run.run_id

def test_demo_cli_rejects_test_db_and_preserves_existing_stores(case):
    from flask import current_app
    current_app.config.update(APP_ENV='demo',MODULE_DEV='B')
    before=db.session.execute(db.select(db.func.count(Store.id))).scalar_one()
    response=current_app.test_cli_runner().invoke(args=['inventory','prepare-b03-demo'])
    assert response.exit_code!=0 and 'system2_b' in response.output
    assert db.session.execute(db.select(db.func.count(Store.id))).scalar_one()==before

def test_forecast_and_risk_are_independent_of_callers_decimal_context(case):
    from decimal import localcontext
    case['rows'][0].sold_qty+=1; db.session.flush()
    first=generate(case).items[0]
    with localcontext() as context:
        context.prec=2
        second=generate(case).items[0]
    assert (first.mu,first.target_stock,first.raw_qty,first.suggested_qty)==(second.mu,second.target_stock,second.raw_qty,second.suggested_qty)
    assert first.timeline_committed==second.timeline_committed and first.warnings==second.warnings
