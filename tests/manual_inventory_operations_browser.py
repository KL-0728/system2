"""Read-only actual Edge login and mobile check against the B05 demo."""
import os, sys
from pathlib import Path
from threading import Thread
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import Store, Inventory, BusinessClock
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

app=create_app()
with app.app_context():
    assert app.config['APP_ENV']=='demo' and app.config['MODULE_DEV']=='B'
    assert (db.engine.url.database or '').startswith('system2_b') and db.engine.url.database.endswith('_demo')
    store=db.session.execute(db.select(Store).where(Store.code=='B05DEMO')).scalar_one()
    sid=store.id
    def state():
        db.session.expire_all()
        return ([db.session.scalar(db.select(db.func.count()).select_from(t)) for t in db.metadata.tables.values()],
            [(s.id,s.calculation_version) for s in db.session.execute(db.select(Store).order_by(Store.id)).scalars()],
            [(i.id,i.book_physical_qty,i.book_unsellable_qty,i.version,i.reconciliation_required)
             for i in db.session.execute(db.select(Inventory).order_by(Inventory.id)).scalars()],
            db.session.get(BusinessClock,1).business_anchor)
    before=state();db.session.rollback()
    server=make_server('127.0.0.1',0,app,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as runner:
            browser=runner.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':390,'height':900})
            errors=[];page.on('pageerror',lambda e: errors.append(str(e)))
            base=f'http://127.0.0.1:{server.server_port}'
            page.goto(base+'/login')
            page.locator('#username').fill('b05manager')
            page.locator('#password').fill(os.environ['DEMO_PASSWORD'])
            page.get_by_role('button',name='登入',exact=True).click()
            identity=page.request.get(base+'/api/auth/me').json()
            assert identity['username']=='b05manager'
            page.goto(base+f'/store/data?store_id={sid}')
            page.wait_for_function("!document.querySelector('#submit-movement').disabled")
            status=page.request.get(base+f'/api/inventory/status?store_id={sid}').json()
            assert status['code']=='B05DEMO'
            assert [(i['physical_book'],i['unsellable_book'],i['h']) for i in status['items']]==[
                (32,2,30),(-5,0,None),(30,0,None),(8,0,8)]
            tasks=page.request.get(base+f'/api/inventory/reconciliations?store_id={sid}').json()['items']
            assert len(tasks)==2 and all(t['status']=='OPEN' and t['due_at'] and not t['overdue'] for t in tasks)
            assert '負責角色：店長' in page.locator('#reconciliation-list').inner_text()
            assert page.request.get(base+'/api/inventory/status?store_id=1').status==404
            page.evaluate("document.documentElement.style.fontSize='20px'")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            artifacts=Path('instance/browser-check');artifacts.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(artifacts/'b05-demo-start-390.png'),full_page=True)
            page.goto(base+f'/store/replenishment?store_id={sid}')
            page.wait_for_function("!document.querySelector('#generate-run').disabled")
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not errors
            browser.close()
    finally:
        server.shutdown();thread.join(timeout=5)
    assert state()==before
    print(f'PASS real Edge demo: b05manager / B05DEMO #{sid}, initial 32/2/H30, -5/Hnull, 30/Hnull, 8/H8, two OPEN deadlines, other-store404.')
    print('PASS read-only mobile 390px/20px data and replenishment pages; all table counts, stock/store versions and business clock preserved.')
