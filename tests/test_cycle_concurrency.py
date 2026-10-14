from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from app.extensions import db
from app.models import BusinessClock, Store, DeliveryCycle
from test_ordering_concurrency import committed_app
from conftest import login


def test_two_real_connections_prepare_same_cross_day_cycles(committed_app, monkeypatch):
    clock=db.session.get(BusinessClock,1)
    clock.business_anchor+=timedelta(days=1)
    store=db.session.execute(db.select(Store).where(Store.code=='DEMO1')).scalar_one()
    store_id=store.id
    db.session.commit();db.session.remove()
    clients=[committed_app.test_client(),committed_app.test_client()]
    for client in clients:
        with committed_app.app_context():assert login(client).status_code==200
    import app.modules.inventory.replenishment_routes as module
    # register() binds the module authorize function in each endpoint closure.
    original=module.authorize
    barrier=Barrier(2)
    def authorize(*args,**kwargs):
        if kwargs.get('lock'):barrier.wait(timeout=10)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'authorize',authorize)
    def request(client):
        with committed_app.app_context():return client.get(f'/api/replenishment/context?store_id={store_id}')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(request,c) for c in clients]
        results=[f.result(timeout=20) for f in futures]
    assert all(r.status_code==200 for r in results),[r.json for r in results]
    assert results[0].json['cycles']==results[1].json['cycles']
    assert results[0].json['store_version']==results[1].json['store_version']
    cycle_ids=[c['id'] for c in results[0].json['cycles']]
    assert db.session.execute(db.select(db.func.count(DeliveryCycle.id)).where(DeliveryCycle.id.in_(cycle_ids))).scalar_one()==3
