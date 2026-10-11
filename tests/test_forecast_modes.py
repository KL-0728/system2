"""B04 real manual/direct modes with immutable snapshots and v1 C consumption."""
from datetime import timedelta
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import ManualForecastOverride, Inventory, ReplenishmentRun, RunItem, SalesDaily, BusinessClock, Store, User
from app.contracts import dto_dict
from app.services.clock import utc_naive
from app.services.errors import DomainError
from app.services.manual_forecasting import ManualForecastService
from app.providers import register_provider
from app.testing.providers import ControlledOpenOrders
from test_replenishment import case, generate, codes
from conftest import login

def save(c,value='5.125',product=0):
    return ManualForecastService().save(store_id=c['store'].id,product_id=c['stocks'][product].product_id,
        actor_id=c['actor'].id,daily_demand=value,reason='本地活動需求，依件數調整每日預測',
        expected_version=c['store'].calculation_version,session=db.session)

def run_manual(c,product=0,confirmed=True):
    pid=c['stocks'][product].product_id
    return c['service'].generate(store_id=c['store'].id,actor_id=c['actor'].id,cycle_id=c['cycles'][0].id,
        expected_version=c['store'].calculation_version,session=db.session,modes={pid:'manual'},
        manual_confirmations=(pid,) if confirmed else ())

def run_direct(c,product=1,final=1000,need_qty=1000):
    pid=c['stocks'][product].product_id
    return c['service'].generate(store_id=c['store'].id,actor_id=c['actor'].id,cycle_id=c['cycles'][0].id,
        expected_version=c['store'].calculation_version,session=db.session,modes={pid:'direct'},
        special_needs={pid:dict(need_date='2026-10-10',need_qty=need_qty,
            reason='週末社區活動需雨衣，已核對件數',arrangement='到貨後直接交付活動單位')},
        direct_quantities={pid:final})

def evaluate(c,run,final=None,confirm=(),now=None,cycle=0):
    return c['service'].evaluate(run_id=run.run_id,store_id=run.store_id,actor_id=c['actor'].id,
        cycle_id=c['cycles'][cycle].id,final_quantities=final or {},manual_confirmations=confirm,
        evaluated_at=now or c['b']+timedelta(minutes=20),session=db.session)

def missing(c,product=1):
    row=db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id==c['store'].id,
        SalesDaily.product_id==c['stocks'][product].product_id,SalesDaily.business_date==c['b'].date())).scalar_one()
    db.session.delete(row);db.session.flush()

@pytest.mark.parametrize('value',[True,False,5,5.125,None,'NaN','Infinity','-1','1.0001','1000000.001','1e3',' 5','5.',''])
def test_manual_invalid_values_are_atomic(case,value):
    before=case['store'].calculation_version
    with pytest.raises(DomainError):save(case,value)
    assert case['store'].calculation_version==before
    assert db.session.execute(db.select(db.func.count(ManualForecastOverride.id))).scalar_one()==0

@pytest.mark.parametrize('value',['0','0.001','5.125','1000000'])
def test_manual_valid_decimal_values_and_expiry(case,value):
    result=save(case,value); ref=result['manual_forecast']
    assert Decimal(ref['daily_demand'])==Decimal(value)
    assert ref['override_id'] and ref['actor_id']==case['actor'].id
    assert ref['valid_until']==(case['b']+timedelta(days=7)).isoformat()
    assert result['store_version']==2 and case['stocks'][0].book_physical_qty==8

def test_manual_revisions_and_old_run_stay_immutable(case):
    old=save(case); run=run_manual(case); item=run.items[0]
    assert item.mode=='manual' and item.mu==Decimal('5.125')
    assert (item.target_stock,item.raw_qty,item.suggested_qty)==(Decimal('20.25'),Decimal('12.25'),18)
    assert item.manual_forecast['override_id']==old['manual_forecast']['override_id']
    assert 'MANUAL_FORECAST' in codes(item) and 'FORECAST_INSUFFICIENT' not in codes(item)
    new=save(case,'8.5')
    assert new['manual_forecast']['version']==2
    assert new['manual_forecast']['override_id']!=old['manual_forecast']['override_id']
    old_read=case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session)
    assert old_read.items[0].mu==Decimal('5.125')
    with pytest.raises(DomainError) as error:evaluate(case,run,confirm=(item.product_id,))
    assert error.value.code=='VERSION_CONFLICT'
    nested=db.session.begin_nested()
    db.session.get(ManualForecastOverride,old['manual_forecast']['override_id']).reason='改寫'
    with pytest.raises(DomainError) as error:db.session.flush()
    assert error.value.code=='IMMUTABLE_RECORD';nested.rollback()

def test_manual_selection_is_explicit_and_confirmation_required(case):
    save(case)
    assert generate(case).items[0].mode=='model'  # Carrying a value does not select it.
    with pytest.raises(DomainError) as error:run_manual(case,confirmed=False)
    assert error.value.code=='MANUAL_CONFIRMATION_REQUIRED'
    run=run_manual(case);pid=run.items[0].product_id
    unconfirmed=evaluate(case,run).items[0]
    assert unconfirmed.mode=='manual' and 'FORECAST_INSUFFICIENT' in codes(unconfirmed)
    confirmed=evaluate(case,run,confirm=(pid,)).items[0]
    assert 'FORECAST_INSUFFICIENT' not in codes(confirmed)
    assert 'MANUAL_FORECAST' in codes(confirmed)
    assert dto_dict(case['service'].get_run(run_id=run.run_id,store_id=run.store_id,actor_id=case['actor'].id,session=db.session))==dto_dict(run)

def test_manual_can_replace_missing_quality_without_hiding_fact(case):
    missing(case,product=0);save(case)
    item=run_manual(case).items[0]
    assert item.mode=='manual' and not item.input_snapshot['forecast_quality']['valid']
    assert item.input_snapshot['forecast_quality']['invalid_days']
    assert item.suggested_qty==18 and 'FORECAST_INSUFFICIENT' not in codes(item)

@pytest.mark.parametrize('expired',[True,False])
def test_expired_latest_value_never_falls_back_to_older_valid(case,expired):
    # Explicit synthetic historical reference, never modify a saved override.
    for version,expiry in [(1,case['b']+timedelta(days=2)),(2,case['b']+timedelta(minutes=20 if expired else 30))]:
        db.session.add(ManualForecastOverride(store_id=case['store'].id,product_id=case['stocks'][0].product_id,
            daily_demand=Decimal(5),reason='合成期限邊界',actor_id=case['actor'].id,
            created_at=utc_naive(case['b']-timedelta(days=1)),valid_until=utc_naive(expiry),version=version))
    db.session.flush()
    item=run_manual(case).items[0]
    assert (item.mode=='unavailable')==expired
    if expired:assert item.mu is None and item.manual_forecast is None
    else:
        run=run_manual(case)
        later=evaluate(case,run,confirm=(item.product_id,),now=case['b']+timedelta(minutes=30)).items[0]
        assert later.mode=='unavailable' and later.mu is None and 'FORECAST_INSUFFICIENT' in codes(later)

@pytest.mark.parametrize('mode',['manual','direct'])
@pytest.mark.parametrize('problem',['negative','gap','reconciliation'])
def test_modes_cannot_bypass_inventory(case,mode,problem):
    missing(case,product=1);stock=case['stocks'][1]
    if problem=='negative':stock.book_physical_qty=-1
    elif problem=='gap':stock.counted_at-=timedelta(days=1)
    else:stock.reconciliation_required=True
    db.session.flush()
    if mode=='manual':save(case,product=1);run=run_manual(case,product=1)
    else:run=run_direct(case)
    item=run.items[1]
    assert item.h is None and item.mode=='unavailable'
    assert all(v is None for v in (item.mu,item.target_stock,item.raw_qty,item.suggested_qty))
    assert codes(item)&{'INVENTORY_GAP','NEGATIVE_BOOK'}

def test_direct_null_no_curves_and_conservative_capacity_no_double_add(case):
    missing(case)
    run=run_direct(case);item=run.items[1]
    assert item.mode=='direct' and item.h==20
    assert all(v is None for v in (item.mu,item.target_stock,item.raw_qty,item.suggested_qty))
    assert not item.timeline_committed and not item.timeline_with_pending and item.manual_forecast is None
    assert {'DIRECT_ORDER','SPECIAL_DEMAND','LARGE_QUANTITY','CAPACITY'}<=codes(item)
    bound=next(w.details['conservative_capacity'] for w in item.warnings if w.code=='DIRECT_ORDER')
    assert bound['upper_bound_with_pending']==1020 and bound['candidate_qty']==1000
    stored=db.session.get(RunItem,item.run_item_id)
    assert stored.output_snapshot['conservative_capacity']==bound
    result=evaluate(case,run,final={item.product_id:1200}).items[1]
    assert next(w.details['conservative_capacity'] for w in result.warnings if w.code=='DIRECT_ORDER')['upper_bound_with_pending']==1220
    assert run.items[1].input_snapshot['special_need']['need_qty']==1000
    assert run.items[1].suggested_qty is None

def test_direct_valid_model_rejected_and_pack_not_autochanged(case):
    with pytest.raises(DomainError) as error:run_direct(case)
    assert error.value.code=='DIRECT_REQUIRES_INSUFFICIENT'
    missing(case,product=0);run=run_direct(case,product=0,final=1000)
    assert 'INVALID_PACK' in codes(run.items[0])
    assert next(w.details['conservative_capacity'] for w in run.items[0].warnings if w.code=='DIRECT_ORDER')['candidate_qty']==1000
    zero=evaluate(case,run,final={run.items[0].product_id:0}).items[0]
    assert 'INVALID_QUANTITY' in codes(zero)

def test_direct_source_risk_and_capacity_kept(case):
    missing(case,product=0)
    register_provider('open_orders',ControlledOpenOrders('expired'),test_only=True)
    item=run_direct(case,product=0,final=30,need_qty=30).items[0]
    assert item.sources[0].bucket=='RISK' and 'LOGISTICS_RISK' in codes(item)
    bound=next(w.details['conservative_capacity'] for w in item.warnings if w.code=='DIRECT_ORDER')
    assert bound['upper_bound_with_pending']==50  # H8 + Q30 + risk12; no sales subtracted.

def test_manual_overflow_blocks_and_no_truncation(case):
    save(case,'1000000');item=run_manual(case).items[0]
    assert item.mode=='unavailable' and item.suggested_qty is None and 'INVALID_QUANTITY' in codes(item)

def test_historical_note_is_info_keeps_sales_and_stock(case):
    row=case['rows'][0];before=row.sold_qty;stock=case['stocks'][0].book_physical_qty
    service=ManualForecastService()
    result=service.annotate(store_id=case['store'].id,product_id=row.product_id,actor_id=case['actor'].id,
        business_date=row.business_date.isoformat(),note='歷史社區活動銷售，仍照常納入平均',
        expected_version=case['store'].calculation_version,expected_sales_version=row.version,session=db.session)
    assert row.sold_qty==before and case['stocks'][0].book_physical_qty==stock
    run=generate(case);item=run.items[0]
    assert item.mu==20 and 'HISTORICAL_EVENT' in codes(item) and 'SPECIAL_DEMAND' not in codes(item)
    warning=next(w for w in item.warnings if w.code=='HISTORICAL_EVENT')
    assert warning.level=='info' and item.input_snapshot['sales'][0]['event_note']
    again=service.annotate(store_id=case['store'].id,product_id=row.product_id,actor_id=case['actor'].id,
        business_date=row.business_date.isoformat(),note=row.event_note,expected_version=result['store_version'],
        expected_sales_version=result['sales_version'],session=db.session)
    assert again['unchanged'] and again['store_version']==result['store_version']

def test_manual_save_rollback_and_permissions(case):
    nested=db.session.begin_nested();save(case);nested.rollback()
    assert db.session.execute(db.select(db.func.count(ManualForecastOverride.id))).scalar_one()==0
    for name,status in [('manager2',404),('operator',403)]:
        actor=db.session.execute(db.select(User).where(User.username==name)).scalar_one()
        with pytest.raises(DomainError) as error:
            ManualForecastService().save(store_id=case['store'].id,product_id=case['stocks'][0].product_id,
                actor_id=actor.id,daily_demand='5',reason='合成權限',expected_version=1,session=db.session)
        assert error.value.status==status

def test_new_api_csrf_and_context_reference(case,client):
    login(client);pid=case['stocks'][0].product_id
    body=dict(store_id=case['store'].id,product_id=pid,daily_demand='5.125',reason='本次本地需求',
              expected_version=case['store'].calculation_version)
    assert client.post('/api/replenishment/manual-forecasts',json=body).status_code==400
    token=client.get('/api/auth/csrf').json['csrf_token']
    response=client.post('/api/replenishment/manual-forecasts',json=body,headers={'X-CSRFToken':token})
    assert response.status_code==201, response.json
    context=client.get('/api/replenishment/context').json
    assert context['products'][0]['latest_manual_forecast']['daily_demand']=='5.125'
    assert context['products'][0]['latest_manual_forecast']['expired'] is False
    body=dict(store_id=case['store'].id,cycle_id=case['cycles'][0].id,expected_version=context['store_version'],
        modes={str(pid):'manual'},manual_confirmations=[pid])
    response=client.post('/api/replenishment/runs',json=body,headers={'X-CSRFToken':token})
    assert response.status_code==201 and response.json['items'][0]['mode']=='manual'

@pytest.mark.parametrize('mode',['manual','direct'])
def test_real_b_modes_are_consumed_by_c_and_require_fresh_ack(case,client,mode):
    from test_submission import _write, _save, _preview, _submit_body
    from app.models import OrderItem
    if mode=='manual':
        save(case); run=run_manual(case); selected=run.items[0]; final=selected.suggested_qty
    else:
        missing(case); run=run_direct(case); selected=run.items[1]; final=1000
    db.session.commit()
    assert login(client).status_code==200
    assert _write(client,'POST','/api/ordering/acknowledgement',{'acknowledged':True}).status_code==200
    created=_write(client,'POST','/api/order-drafts',dict(store_id=run.store_id,run_id=run.run_id,cycle_id=run.cycle_id))
    assert created.status_code==201,created.json
    def select(value, original):
        if value['product_id']!=selected.product_id:
            return dict(value,final_qty=0,reason_code='skip',reason='本次僅核對指定品項')
        return dict(value,final_qty=final,reason_code='local_demand',
            reason='社區活動需求已核對件數與存放交付方式',
            special_need=selected.input_snapshot.get('special_need'),
            manual_forecast_acknowledged=False)
    draft=_save(client,created.json,select)
    if mode=='manual':
        blocked=_write(client,'POST',f"/api/order-drafts/{draft['id']}/preview",{'expected_version':draft['version']})
        assert blocked.status_code==422
        draft=_save(client,draft,lambda value,original:dict(value,
            manual_forecast_acknowledged=value['product_id']==selected.product_id))
    preview=_preview(client,draft)
    assert preview['confirmation_token'] and preview['snapshot']['important_product_ids']==[selected.product_id]
    item=next(i for i in preview['snapshot']['items'] if i['product_id']==selected.product_id)
    assert item['mode']==mode and item['final_qty']==final
    if mode=='direct':
        assert item['mu'] is None and item['suggested_qty'] is None
        assert not item['timeline_committed'] and not item['timeline_with_pending']
    else:
        assert item['manual_forecast']['override_id']==selected.manual_forecast['override_id']
    path=f"/api/order-drafts/{draft['id']}/submit"
    unconfirmed=_write(client,'POST',path,_submit_body(draft,preview),{'Idempotency-Key':f'b04-{mode}-no-ack'})
    assert unconfirmed.status_code==422
    acks=[dict(product_id=selected.product_id,warning_version='1',acknowledged=True,
        handling='special_arrangement',reason='已核對需求及存放交付安排')]
    submitted=_write(client,'POST',path,_submit_body(draft,preview,acks),{'Idempotency-Key':f'b04-{mode}-ack'})
    assert submitted.status_code==201,submitted.json
    items=db.session.execute(db.select(OrderItem).where(OrderItem.order_id==submitted.json['order_id'])).scalars().all()
    assert len(items)==1 and items[0].original_qty==final
    assert case['stocks'][0].book_physical_qty==8  # Ordering never changes the B stock.

def test_context_detects_wrong_business_date_interval(case):
    row=case['rows'][0];row.interval_start-=timedelta(days=1);row.interval_end-=timedelta(days=1)
    db.session.flush()
    products=ManualForecastService().options(store_id=case['store'].id,actor_id=case['actor'].id,session=db.session)
    assert not products[0]['forecast_valid']
    assert generate(case).items[0].mode=='unavailable'

def test_note_missing_day_and_stale_versions_do_not_change_stock(case):
    missing(case); pid=case['stocks'][1].product_id; service=ManualForecastService()
    body=dict(store_id=case['store'].id,product_id=pid,actor_id=case['actor'].id,
        business_date=case['b'].date().isoformat(),note='歷史註記不補檔',
        expected_version=1,expected_sales_version=1,session=db.session)
    with pytest.raises(DomainError) as error:service.annotate(**body)
    assert error.value.status==404 and case['store'].calculation_version==1
    save(case)
    with pytest.raises(DomainError) as error:service.annotate(**body)
    assert error.value.code=='VERSION_CONFLICT'
    with pytest.raises(DomainError) as error:service.save(store_id=case['store'].id,product_id=pid,
        actor_id=case['actor'].id,daily_demand='5',reason='過期門市版本',expected_version=1,session=db.session)
    assert error.value.code=='VERSION_CONFLICT'
    assert db.session.execute(db.select(db.func.count(ManualForecastOverride.id))).scalar_one()==1
    assert case['stocks'][1].book_physical_qty==20

@pytest.mark.parametrize('change',[
    {'modes':{'wrong':'manual'}},
    {'modes':{1:'invalid'}},
    {'modes':{1:'manual'},'manual_confirmations':[True]},
    {'modes':{1:'direct'},'direct_quantities':{1:0}},
    {'modes':{1:'direct'},'direct_quantities':{1:1000001}},
    {'modes':{1:'direct'},'direct_quantities':{1:30},'special_needs':{1:{}}},
])
def test_bad_mode_payload_writes_no_run(case,change):
    with pytest.raises(DomainError):
        case['service'].generate(store_id=case['store'].id,actor_id=case['actor'].id,
            cycle_id=case['cycles'][0].id,expected_version=1,session=db.session,**change)
    assert db.session.execute(db.select(db.func.count(ReplenishmentRun.id))).scalar_one()==0

@pytest.mark.parametrize('days,hour',[(7,12),(7,23),(2,21)])
def test_expiry_uses_configured_policy_and_taipei_day(case,days,hour):
    from test_replenishment import policy
    policy(case,manual_valid_days=days)
    now=case['b'].replace(hour=hour-8)
    db.session.get(BusinessClock,1).business_anchor=utc_naive(now)
    db.session.flush()
    result=save(case)['manual_forecast']
    assert result['valid_until']==(case['b']+timedelta(days=days)).isoformat()
    assert result['created_at']==now.isoformat()

def test_b04_demo_cli_refuses_unowned_test_database(case):
    from flask import current_app
    current_app.config.update(APP_ENV='demo',MODULE_DEV='B')
    before=db.session.execute(db.select(db.func.count(Store.id))).scalar_one()
    response=current_app.test_cli_runner().invoke(args=['inventory','prepare-b04-demo'])
    assert response.exit_code!=0 and 'system2_b' in response.output
    assert db.session.execute(db.select(db.func.count(Store.id))).scalar_one()==before

def test_manual_calculation_ignores_callers_decimal_precision(case):
    from decimal import localcontext
    save(case)
    first=run_manual(case).items[0]
    with localcontext() as context:
        context.prec=2
        second=run_manual(case).items[0]
    assert (first.mu,first.target_stock,first.raw_qty,first.suggested_qty)==(second.mu,second.target_stock,second.raw_qty,second.suggested_qty)
    assert first.timeline_committed==second.timeline_committed
