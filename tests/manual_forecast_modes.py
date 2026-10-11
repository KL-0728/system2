"""Guarded real Edge B04 demo; additive manual revision/runs, no stock/clock changes."""
import os
import sys
from pathlib import Path
from threading import Thread
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import Store, Inventory, BusinessClock, Product
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

application=create_app()
with application.app_context():
    assert application.config['APP_ENV']=='demo' and application.config['MODULE_DEV']=='B'
    assert (db.engine.url.database or '').startswith('system2_b') and db.engine.url.database.endswith('_demo')
    store=db.session.execute(db.select(Store).where(Store.code=='B04DEMO')).scalar_one()
    pid=db.session.execute(db.select(Product.id).where(Product.sku=='SKU03')).scalar_one()
    rain_id=db.session.execute(db.select(Product.id).where(Product.sku=='SKU02')).scalar_one()
    def protected_state():
        db.session.expire_all()
        return ([(s.id,s.calculation_version) for s in db.session.execute(db.select(Store)
            .where(Store.code!='B04DEMO').order_by(Store.id)).scalars()],
            [(s.id,s.physical_qty,s.unsellable_qty,s.book_physical_qty,s.book_unsellable_qty,s.version,s.counted_at)
                for s in db.session.execute(db.select(Inventory).order_by(Inventory.id)).scalars()],
            db.session.get(BusinessClock,1).business_anchor)
    before=protected_state();db.session.rollback()
    server=make_server('127.0.0.1',0,application,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as runner:
            browser=runner.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':390,'height':900})
            errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
            base=f'http://127.0.0.1:{server.server_port}'
            page.goto(base+'/login')
            page.locator('#username').fill('b04manager');page.locator('#password').fill(os.environ['DEMO_PASSWORD'])
            page.get_by_role('button',name='登入',exact=True).click()
            page.goto(base+'/store/replenishment')
            def wait(text):
                page.wait_for_function("(text)=>document.querySelector('#run-message').textContent.includes(text)",arg=text)
                page.wait_for_function("!document.querySelector('#generate-run').disabled")
            page.wait_for_function("!document.querySelector('#generate-run').disabled")
            page.locator('.forecast-choices > summary').click()
            manual=page.locator('[data-forecast-product="'+str(pid)+'"]')
            manual.locator('[data-field=mode]').select_option('manual')
            manual.locator('[data-field=daily-demand]').fill('5.125')
            manual.locator('[data-field=manual-reason]').fill('合成 B04 驗收：已核對每日需求與社區活動存放安排')
            manual.locator('[data-action=save-manual]').click();wait('人工預測已保存')
            manual.locator('[data-field=confirmed]').check()
            page.locator('#generate-run').click();wait('快照已保存')
            item=page.locator('[data-sku=SKU03]')
            assert '5.125' in item.inner_text() and '13件' in item.inner_text()
            assert '30件' in page.locator('[data-sku=SKU01]').inner_text()
            assert 'HISTORICAL_EVENT' in page.locator('[data-sku=SKU01]').inner_text()
            blocked=page.locator('[data-sku=SKU04]')
            assert 'NEGATIVE_BOOK' in blocked.inner_text() and blocked.locator('input[type=number]').is_disabled()
            artifacts=Path('instance/browser-check');artifacts.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(artifacts/'b04-demo-manual-390.png'),full_page=True)
            manual_run=page.locator('#saved-run').input_value()
            manual.locator('[data-field=mode]').select_option('model')
            direct=page.locator('[data-forecast-product="'+str(rain_id)+'"]')
            direct.locator('[data-field=mode]').select_option('direct')
            for field,value in [('need-date','2026-10-10'),('need-qty','1000'),
                ('special-reason','社區活動需要一千件雨衣，已核對件數'),
                ('arrangement','到貨後直接交付活動單位'),('direct-qty','1000')]:
                direct.locator('[data-field='+field+']').fill(value)
            page.locator('#generate-run').click();wait('快照已保存')
            rain=page.locator('[data-sku=SKU02]')
            assert '無法計算' in rain.inner_text() and '1020件' in rain.inner_text()
            assert rain.locator('input[type=number]').input_value()=='1000'
            assert rain.locator('svg').count()==0
            assert all(code in rain.inner_text() for code in ['DIRECT_ORDER','SPECIAL_DEMAND','CAPACITY','LARGE_QUANTITY'])
            page.screenshot(path=str(artifacts/'b04-demo-direct-390.png'),full_page=True)
            direct_run=page.locator('#saved-run').input_value()
            assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            browser.close()
    finally:
        server.shutdown();thread.join(timeout=5)
    assert protected_state()==before
    print(f'PASS real Edge B04 demo: manual run #{manual_run} (5.125/Q13), direct run #{direct_run} (1000, null model, capacity1020).')
    print('PASS inventory/clock/other stores unchanged; only a B04 manual revision, store-version bump, audit and two runs added.')
