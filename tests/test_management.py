"""A04 permissions, versioned policies and revocation on isolated MySQL."""
from datetime import timedelta
import pytest
from app.extensions import db
from app.models import Store, Product, PolicyVersion, User, BusinessClock, AuditEvent
from app.services.clock import aware
from flask import g
from conftest import login as original_login
from test_submission import _write as original_write


def login(*args, **kwargs):
    g.pop('csrf_token', None)
    return original_login(*args, **kwargs)


def _write(*args, **kwargs):
    g.pop('csrf_token', None)
    return original_write(*args, **kwargs)


def admin(client):
    assert login(client, 'admin').status_code == 200
    response = client.get('/api/admin/catalog')
    assert response.status_code == 200
    return response.json


@pytest.mark.parametrize('username', ['manager1', 'operator'])
def test_admin_access_is_enforced(seeded, client, username):
    assert login(client, username).status_code == 200
    for url in ('/admin', '/api/admin/catalog', '/api/admin/audit', '/api/admin/clock'):
        assert client.get(url).status_code == 403
    assert _write(client, 'POST', '/api/admin/products', {}).status_code == 403


def test_versioned_policy_conflict_and_same_round_recalculation(seeded, client):
    data = admin(client)
    policy = data['policies'][0]
    store = db.session.get(Store, policy['store_id'])
    old_version = store.calculation_version
    old_id = db.session.execute(db.select(PolicyVersion.id).where(
        PolicyVersion.store_id == policy['store_id'], PolicyVersion.product_id == policy['product_id'])).scalar_one()
    db.session.get(BusinessClock, 1).business_anchor += timedelta(minutes=1)
    db.session.commit()
    changed = _write(client, 'PATCH', f"/api/admin/policies/{policy['id']}", {**policy, 'safety_stock': 25})
    assert changed.status_code == 200, changed.json
    assert changed.json['version'] == 2
    assert db.session.get(PolicyVersion, old_id).parameters['safety_stock'] == 10
    assert db.session.get(Store, store.id).calculation_version == old_version+1
    assert _write(client, 'PATCH', f"/api/admin/policies/{policy['id']}", policy).status_code == 409
    from app.services.replenishment import ReplenishmentService
    from app.models import DeliveryCycle
    cycle = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id == store.id)
        .order_by(DeliveryCycle.arrival_at)).scalars().first()
    actor = db.session.execute(db.select(User).where(User.username == 'admin')).scalar_one()
    run = ReplenishmentService().generate(store_id=store.id, actor_id=actor.id, cycle_id=cycle.id,
        expected_version=store.calculation_version, session=db.session)
    assert run.items[0].safety_stock == 25
    assert all(not entry[1] for entry in seeded.extensions['service_providers'].values())


def test_pack_change_updates_all_policies_without_overwriting_history(seeded, client):
    data = admin(client)
    product = data['products'][0]
    response = _write(client, 'PATCH', f"/api/admin/products/{product['id']}", {**product, 'pack_size': 12})
    assert response.status_code == 200, response.json
    policies = client.get('/api/admin/catalog').json['policies']
    assert all(p['pack_size'] == 12 and p['version'] == 2 for p in policies if p['product_id'] == product['id'])
    old = db.session.execute(db.select(PolicyVersion).where(PolicyVersion.product_id == product['id'], PolicyVersion.version == 1)).scalars().all()
    assert {p.parameters['pack_size'] for p in old} == {6}


def test_create_user_revoke_session_and_no_password_in_audit(seeded, client):
    data = admin(client)
    manager = next(u for u in data['users'] if u['username'] == 'manager1')
    other = seeded.test_client()
    assert login(other).status_code == 200
    assert _write(client, 'PATCH', f"/api/admin/users/{manager['id']}", {**manager, 'active':False}).status_code == 200
    assert other.get('/api/auth/me').status_code == 401
    body = dict(username='new-manager', role='manager', store_ids=[data['stores'][0]['id']], active=True, password='New-synthetic-password')
    assert _write(client, 'POST', '/api/admin/users', body).status_code == 201
    assert _write(client, 'POST', '/api/admin/users', body).status_code == 409
    events = client.get('/api/admin/audit').json
    assert 'password_hash' not in str(events) and body['password'] not in str(events)
    assert login(other, 'new-manager', body['password']).status_code == 200
    own = next(u for u in client.get('/api/admin/catalog').json['users'] if u['username'] == 'admin')
    assert _write(client, 'PATCH', f"/api/admin/users/{own['id']}", {**own, 'active':False}).status_code == 422


@pytest.mark.parametrize('body', [[], None, {'time':'2026-10-08T21:01'}, {'time':'bad'}, {'time':'2026-10-08T21:01+08:00','paused':1}])
def test_invalid_clock_is_rejected(seeded, client, body):
    admin(client)
    assert _write(client, 'POST', '/api/admin/clock', body).status_code == 422


def test_clock_forward_backwards_and_production_guard(seeded, client):
    admin(client)
    target = (aware(db.session.get(BusinessClock, 1).business_anchor)+timedelta(minutes=10)).isoformat()
    assert _write(client, 'POST', '/api/admin/clock', {'time':target}).status_code == 200
    assert _write(client, 'POST', '/api/admin/clock', {'time':'2026-10-08T21:00+08:00'}).status_code == 409
    seeded.config['APP_ENV'] = 'production'
    assert _write(client, 'POST', '/api/admin/clock', {'time':target}).status_code == 403


@pytest.mark.parametrize('field,value', [('pack_size',0),('pack_size',True),('pack_size',1.5),('active','false'),('name','')])
def test_product_input_validation(seeded, client, field, value):
    row = admin(client)['products'][0]
    response = _write(client, 'PATCH', f"/api/admin/products/{row['id']}", {**row, field:value})
    assert response.status_code == 422


def test_new_store_policy_starts_unverified_and_cycles_are_idempotent(seeded,client):
    data=admin(client)
    response=_write(client,'POST','/api/admin/stores',dict(code='NEWSTORE',name='新示範門市',active=True))
    assert response.status_code==201
    store_id=response.json['id']
    policy=_write(client,'POST','/api/admin/policies',dict(store_id=store_id,
        product_id=data['products'][0]['id'],lead_days=4,safety_stock=5,capacity=50,active=True))
    assert policy.status_code==201,policy.json
    from app.services.inventory import InventoryService
    from app.services.clock import business_now, round_window
    state=InventoryService().get_integrity(store_id=store_id,product_id=data['products'][0]['id'],
        baseline_at=round_window(business_now())[0],session=db.session)
    assert not state.usable and state.baseline_counted_at is None
    first=_write(client,'POST','/api/admin/cycles/prepare',{'store_id':store_id})
    second=_write(client,'POST','/api/admin/cycles/prepare',{'store_id':store_id})
    assert first.status_code==second.status_code==200
    assert first.json['added']==4 and second.json['added']==0
    created=_write(client,'POST','/api/admin/users',dict(username='new-store-manager',role='manager',
        store_ids=[store_id],active=True,password='New-synthetic-password'))
    assert created.status_code==201
    from app.services.sales import SalesService
    from app.models import Inventory
    sales=SalesService()
    day=round_window(business_now())[0].date().isoformat()
    sku=data['products'][0]['sku']
    payload=dict(store_id=store_id,import_mode='daily_posting',
        csv_text=f'source_batch_id,store_code,sku,business_date,sold_qty,was_stockout,is_open\nNEW-DAILY,NEWSTORE,{sku},{day},0,0,1\n')
    actor_id=created.json['id']
    validation=sales.validate(payload=payload,actor_id=actor_id,session=db.session)
    assert validation['valid'],validation
    sales.commit(payload=payload,actor_id=actor_id,validation_token=validation['validation_token'],session=db.session)
    inventory=db.session.execute(db.select(Inventory).where(Inventory.store_id==store_id,
        Inventory.product_id==data['products'][0]['id'])).scalar_one()
    service=InventoryService()
    service.submit_count(store_id=store_id,product_id=inventory.product_id,actor_id=actor_id,
        cutoff_at=round_window(business_now())[0],physical_qty=20,unsellable_qty=0,
        expected_version=inventory.version,request_key='new-store-first-count',reason='首次門市核對',session=db.session)
    verified=service.get_integrity(store_id=store_id,product_id=inventory.product_id,
        baseline_at=round_window(business_now())[0],session=db.session)
    assert verified.usable and verified.h==20
