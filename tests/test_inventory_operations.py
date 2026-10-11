"""B05 real MySQL operations, replay, authorization and independent writer races."""
from dataclasses import asdict
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy.orm import Session
from app.extensions import db
from app.models import (Inventory, InventoryMovement, InventoryReconciliation, AuditEvent,
                        BusinessClock, User)
from app.contracts import InventoryMutation
from app.services.clock import business_now, utc_naive
from app.services.errors import DomainError
from app.services.inventory_operations import InventoryOperations
from test_inventory import case, concurrent_case, move, post_daily, count_args, advance
from conftest import login

def removal(c,kind='disposal',**changes):
    service,store,actor,row,b=c
    return dict(store_id=store.id,product_id=row.product_id,actor_id=actor.id,kind=kind,
        qty=2,expected_version=row.version,source_id='B05-damaged-1',occurred_at=business_now(),
        reason='已核對損壞品實物離店，保留收貨來源',session=db.session)|changes

def damaged(c):
    # Real B receipt-style input; D fulfillment itself remains an A05 integration task.
    return move(c,physical=12,damaged=2,key='B05-receipt')

def state(c):
    row=c[3];store=c[1]
    return (row.book_physical_qty,row.book_unsellable_qty,row.version,store.calculation_version,
        db.session.scalar(db.select(db.func.count(InventoryMovement.id))),
        db.session.scalar(db.select(db.func.count(AuditEvent.id))))

def resolve(c,task,**changes):
    return dict(count_args(c,physical_qty=10,request_key='B05-count-resolution',
        reason='先核對日常銷售再以有效21:00實盤處理'),task_id=task.id,
        expected_task_version=task.version)|changes

@pytest.mark.parametrize('kind',['disposal','return'])
def test_damaged_removal_keeps_h_and_receipt_and_replays(case,kind):
    _,receipt=damaged(case);body=removal(case,kind)
    result=InventoryOperations().remove_damaged(**body)
    row=case[3]
    assert (result.physical_book,result.unsellable_book)==(30,0)
    assert row.physical_qty==20 and row.book_physical_qty-row.book_unsellable_qty==30
    original=db.session.get(InventoryMovement,receipt.movement_id)
    assert (original.physical_delta,original.unsellable_delta)==(12,2)
    snapshot=state(case)
    advance(case[4],minutes=70)
    replay=InventoryOperations().remove_damaged(**body)
    assert replay.replayed and replay.movement_id==result.movement_id and state(case)==snapshot
    with pytest.raises(DomainError) as error:
        InventoryOperations().remove_damaged(**(body|{'reason':'不同理由'}))
    assert error.value.code=='IDEMPOTENCY_CONFLICT'

@pytest.mark.parametrize('qty',[0,-1,1.2,True,None,'2',1000001])
def test_invalid_removal_is_atomic(case,qty):
    damaged(case);before=state(case)
    with pytest.raises(DomainError):InventoryOperations().remove_damaged(**removal(case,qty=qty))
    assert state(case)==before

@pytest.mark.parametrize('changes',[
    {'qty':3},{'kind':'sale'},{'source_id':''},{'reason':''},
    {'expected_version':1},{'occurred_at':'bad'},
])
def test_invalid_versions_sources_and_over_removal(case,changes):
    damaged(case);before=state(case)
    with pytest.raises(DomainError):
        InventoryOperations().remove_damaged(**removal(case,**changes))
    assert state(case)==before

def test_time_covered_future_and_negative_book_keep_history(case):
    damaged(case)
    for at in (case[4],business_now()+timedelta(seconds=1)):
        before=state(case)
        with pytest.raises(DomainError):InventoryOperations().remove_damaged(**removal(case,occurred_at=at))
        assert state(case)==before
    move(case,source='sales',key='B05-negative',physical=-40)
    before=state(case)
    with pytest.raises(DomainError):
        InventoryOperations().remove_damaged(**removal(case))
    assert state(case)==before and case[3].book_physical_qty==-8
    assert case[3].reconciliation_required

def test_negative_case_requires_real_count_and_exact_retry(case):
    post_daily(case,sold=25);advance(case[4])
    task=db.session.execute(db.select(InventoryReconciliation)).scalar_one()
    service=InventoryOperations();body=resolve(case,task)
    result=service.resolve_with_count(**body)
    assert result.physical_delta==15 and case[3].book_physical_qty==10
    assert task.status=='RESOLVED' and task.resolved_by==case[2].id
    assert task.resolution['method']=='count' and task.resolution['revision_id']==result.revision_id
    assert case[0].get_integrity(store_id=case[1].id,product_id=case[3].product_id,
        baseline_at=case[4],session=db.session).h==10
    before=state(case);assert service.resolve_with_count(**body).replayed and state(case)==before
    with pytest.raises(DomainError) as error:
        service.resolve_with_count(**(body|{'expected_task_version':99}))
    assert error.value.code=='IDEMPOTENCY_CONFLICT'
    with pytest.raises(DomainError) as error:
        service.resolve_with_count(**(body|{'request_key':'another'}))
    assert error.value.code=='ALREADY_RESOLVED'

def test_missing_posting_does_not_allow_task_to_be_checked_off(case):
    row=case[3]
    row.reconciliation_required=True
    task=InventoryReconciliation(store_id=case[1].id,product_id=row.product_id,
        source_type='negative_book',source_id='synthetic-missing-daily',reason='待有效盤點',
        created_at=utc_naive(business_now()))
    db.session.add(task);db.session.flush();before=state(case)
    with pytest.raises(DomainError) as error:
        InventoryOperations().resolve_with_count(**resolve(case,task))
    assert error.value.code=='INVENTORY_GAP'
    assert task.status=='OPEN' and state(case)==before

def test_sales_covered_resolution_preserves_latest_movements(case):
    post_daily(case,sold=2);advance(case[4])
    first=case[0].submit_count(**count_args(case))
    move(case,key='after-cutoff',physical=10,at=case[4]+timedelta(minutes=10))
    task=InventoryReconciliation(store_id=case[1].id,product_id=case[3].product_id,
        source_type='sales_covered',source_id='covered-history',reason='已盤點涵蓋銷售更正',
        created_at=utc_naive(business_now()),resolution={'business_date':case[4].date().isoformat(),'batch_id':1})
    db.session.add(task);db.session.flush()
    body=resolve(case,task,physical_qty=20,correction=True,expected_count_version=first.revision)
    result=InventoryOperations().resolve_with_count(**body)
    assert result.physical_delta==0 and case[3].book_physical_qty==30
    assert task.status=='RESOLVED' and task.resolution['batch_id']==1
    assert task.resolution['count_version']==2

@pytest.mark.parametrize('bad', [{'expected_task_version':9},{'product_id':99999}])
def test_reconciliation_resource_versions_and_ids(case,bad):
    post_daily(case,sold=25);advance(case[4])
    task=db.session.execute(db.select(InventoryReconciliation)).scalar_one();before=state(case)
    with pytest.raises(DomainError):InventoryOperations().resolve_with_count(**resolve(case,task,**bad))
    assert task.status=='OPEN' and state(case)==before

def test_operations_outer_rollback(case):
    damaged(case);before=state(case)
    nested=db.session.begin_nested()
    InventoryOperations().remove_damaged(**removal(case));nested.rollback()
    assert state(case)==before

def test_resolving_outer_rollback_keeps_case_open_and_book_negative(case):
    post_daily(case,sold=25);advance(case[4])
    task=db.session.execute(db.select(InventoryReconciliation)).scalar_one();before=state(case)
    nested=db.session.begin_nested()
    InventoryOperations().resolve_with_count(**resolve(case,task));nested.rollback()
    assert task.status=='OPEN' and state(case)==before and case[3].book_physical_qty==-5

def test_manager_api_csrf_history_and_cross_store(case,client):
    damaged(case);db.session.commit();login(client);body=removal(case)
    body={k:v for k,v in body.items() if k not in ('session','kind','actor_id')}
    body['occurred_at']=body['occurred_at'].isoformat()
    assert client.post('/api/inventory/disposals',json=body).status_code==400
    token=client.get('/api/auth/csrf').json['csrf_token']
    response=client.post('/api/inventory/disposals',json=body,headers={'X-CSRFToken':token})
    assert response.status_code==201,response.json
    assert client.post('/api/inventory/disposals',json=body,headers={'X-CSRFToken':token}).status_code==200
    history=client.get('/api/inventory/movements').json['items']
    assert history[0]['source_type']=='disposal' and history[1]['source_type']=='receipt'
    for path in ['/api/inventory/movements','/api/inventory/reconciliations']:
        assert client.get(path+'?store_id=999999').status_code==404
    login(client,'manager2')
    assert client.post('/api/inventory/disposals',json=body,
        headers={'X-CSRFToken':client.get('/api/auth/csrf').json['csrf_token']}).status_code==404
    login(client,'operator')
    assert client.get('/api/inventory/reconciliations').status_code==403

def test_reconciliation_api_records_actor_and_denies_changed_retry(case,client):
    post_daily(case,sold=25);advance(case[4])
    task=db.session.execute(db.select(InventoryReconciliation)).scalar_one()
    db.session.commit();login(client)
    body={k:v for k,v in resolve(case,task).items() if k not in ('session','actor_id','task_id')}
    body['cutoff_at']=body['cutoff_at'].isoformat()
    headers={'X-CSRFToken':client.get('/api/auth/csrf').json['csrf_token']}
    path=f'/api/inventory/reconciliations/{task.id}/resolve'
    assert client.post(path,json=body,headers=headers).status_code==201
    assert client.post(path,json=body,headers=headers).status_code==200
    assert client.post(path,json=body|{'reason':'另一處理理由'},headers=headers).status_code==409
    task_data=client.get('/api/inventory/reconciliations').json['items'][0]
    assert task_data['status']=='RESOLVED' and task_data['resolved_by']==case[2].id
    assert task_data['resolution']['method']=='count'

@pytest.mark.parametrize('same_source',[True,False])
def test_mysql_damaged_removal_race(concurrent_case,same_source):
    app,engine,(store_id,product_id,actor_id),b=concurrent_case
    with app.app_context(),Session(engine) as session,session.begin():
        row=session.execute(db.select(Inventory).where(Inventory.store_id==store_id)).scalar_one()
        case_mutation=InventoryMutation(store_id,product_id,'receipt','B05-race-receipt',2,2,row.version,actor_id,b,'合成收貨兩損壞')
        from app.services.inventory import InventoryService
        InventoryService().apply_movement(mutation=case_mutation,session=session)
    barrier=Barrier(2)
    def worker(index):
        with app.app_context(),Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                with session.begin():
                    result=InventoryOperations().remove_damaged(store_id=store_id,product_id=product_id,
                        actor_id=actor_id,kind='disposal',qty=2,expected_version=2,
                        source_id='same' if same_source else 'source-'+str(index),occurred_at=b,
                        reason='合成報廢競爭',session=session)
                return 'replayed' if result.replayed else 'applied'
            except DomainError as error:return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,range(2)))
    assert sorted(results)==sorted(['applied','replayed' if same_source else 'VERSION_CONFLICT'])
    with Session(engine) as session:
        row=session.execute(db.select(Inventory).where(Inventory.store_id==store_id)).scalar_one()
        assert (row.book_physical_qty,row.book_unsellable_qty,row.version)==(20,0,3)
        assert session.scalar(db.select(db.func.count(InventoryMovement.id)).where(InventoryMovement.store_id==store_id))==2

def test_damaged_removal_does_not_clear_existing_reconciliation(case):
    damaged(case);row=case[3];row.reconciliation_required=True
    db.session.flush()
    InventoryOperations().remove_damaged(**removal(case))
    assert row.reconciliation_required
    assert not case[0].get_integrity(store_id=case[1].id,product_id=row.product_id,
        baseline_at=case[4],session=db.session).usable

@pytest.mark.parametrize('mode',['test','demo'])
def test_b05_demo_guard_refuses_wrong_environment_or_database(case,mode):
    from flask import current_app
    current_app.config.update(APP_ENV=mode,MODULE_DEV='B')
    before=state(case)
    result=current_app.test_cli_runner().invoke(args=['inventory','prepare-b05-demo'])
    assert result.exit_code!=0
    assert ('APP_ENV' if mode=='test' else 'system2_b') in result.output
    assert state(case)==before

def test_reconciliation_deadline_is_frozen_and_overdue_does_not_resolve(case,client):
    post_daily(case,sold=25);advance(case[4])
    task=db.session.execute(db.select(InventoryReconciliation)).scalar_one()
    deadline=task.resolution['due_at']
    assert task.resolution['deadline_hours']==24 and task.resolution['deadline_policy_version']==1
    db.session.get(BusinessClock,1).business_anchor=utc_naive(case[4]+timedelta(days=2,minutes=20))
    db.session.commit();login(client)
    data=client.get('/api/inventory/reconciliations').json['items'][0]
    assert data['overdue'] and data['due_at']==deadline
    assert task.status=='OPEN' and case[3].book_physical_qty==-5
