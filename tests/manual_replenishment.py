"""Real Edge against B's own additive demo. Creates one saved run; never changes stock."""
import os
import sys
from pathlib import Path
from threading import Thread
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import Store, Inventory, BusinessClock
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

application=create_app()
with application.app_context():
    assert application.config['APP_ENV']=='demo' and application.config['MODULE_DEV']=='B'
    name=db.engine.url.database or ''
    assert name.startswith('system2_b') and name.endswith('_demo')
    assert db.session.execute(db.select(Store.id).where(Store.code=='B03DEMO')).first()
    def stock_state():
        db.session.expire_all()
        return ([(s.id,s.code,s.calculation_version) for s in db.session.execute(db.select(Store).order_by(Store.id)).scalars()],
            [(s.id,s.book_physical_qty,s.book_unsellable_qty,s.version,s.counted_at) for s in db.session.execute(db.select(Inventory).order_by(Inventory.id)).scalars()],
            db.session.get(BusinessClock,1).business_anchor)
    before=stock_state(); db.session.rollback()
    server=make_server('127.0.0.1',0,application,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        with sync_playwright() as runner:
            browser=runner.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':390,'height':900})
            errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            base=f'http://127.0.0.1:{server.server_port}'
            page.goto(base+'/login')
            page.locator('#username').fill('b03manager')
            page.locator('#password').fill(os.environ['DEMO_PASSWORD'])
            page.get_by_role('button',name='登入',exact=True).click()
            page.goto(base+'/store/replenishment')
            page.wait_for_function("!document.querySelector('#generate-run').disabled")
            page.locator('#generate-run').click()
            page.wait_for_function("document.querySelector('#run-message').textContent.includes('快照已保存')")
            drink=page.locator('[data-sku=SKU01]'); rain=page.locator('[data-sku=SKU02]'); missing=page.locator('[data-sku=SKU03]')
            assert '42件' in drink.inner_text() and 'PRE_ARRIVAL_STOCKOUT' in drink.inner_text()
            assert '0件' in rain.inner_text() and 'ZERO_SALES' in rain.inner_text()
            assert '無有效建議' in missing.inner_text() and missing.locator('input').is_disabled()
            rain.locator('input').fill('1000'); page.locator('#evaluate-run').click()
            page.wait_for_function("document.querySelector('#run-message').textContent.includes('試算完成')")
            assert all(code in rain.inner_text() for code in ('CAPACITY','LARGE_QUANTITY','DEVIATION'))
            assert rain.locator('input').input_value()=='1000'
            page.locator('#load-run').click()
            page.wait_for_function("document.querySelector('#run-message').textContent.includes('已讀取原快照')")
            assert rain.locator('input').input_value()=='0' and drink.locator('input').input_value()=='42'
            artifacts=Path('instance/browser-check'); artifacts.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(artifacts/'b03-demo-390.png'),full_page=True)
            assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            browser.close()
    finally:
        server.shutdown(); thread.join(timeout=5)
    assert stock_state()==before
    print('PASS B03 demo /store/replenishment: real Edge, H8/mean20/Q42, zero/Q0, missing/null, final1000 warnings, original snapshot preserved.')
    print('PASS all existing store versions, inventory quantities/versions and business clock unchanged. One B03 saved run added.')
