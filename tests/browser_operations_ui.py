"""Review every operational screen with real B/C/D records in isolated MySQL."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.services.replenishment import ReplenishmentService
from test_full_integration import real_order
from browser_fulfillment_full import login, logout


@pytest.fixture
def ui_server(seeded, client):
    order, item, manager, cycle, _ = real_order(seeded, client)
    ReplenishmentService().generate(store_id=order.store_id, actor_id=manager.id,
        cycle_id=cycle.id, expected_version=manager.stores[0].calculation_version, session=db.session)
    db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}',order.id,order.store_id
    finally: server.shutdown();thread.join(timeout=5)


@pytest.mark.parametrize('width',[1440,390,320])
def test_all_role_screens(ui_server,width):
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id=ui_server
    artifacts=Path('instance/browser-check/operations');artifacts.mkdir(parents=True,exist_ok=True)
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':width,'height':960})
        page.set_default_timeout(8000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def check(name):
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
            page.screenshot(path=str(artifacts/f'{name}-{width}.png'),full_page=True)
        page.goto(base+'/login');check('login')
        assert page.locator('[data-password-toggle]').is_visible()
        login(page,base,'manager1');check('manager-home')
        cards=page.locator('.metric-card')
        assert cards.nth(1).locator('strong').inner_text()=='1'
        assert '測試提供者' not in page.locator('body').inner_text()
        pages=[('/store/data','.stock-card','inventory'),('/store/replenishment','#run-cycle option','replenishment'),
            ('/store/ordering','.product-row','ordering'),('/store/orders','.order-card','orders'),
            (f'/store/orders/{order_id}','#order-detail .summary-card','order-detail'),
            ('/store/receiving','#fulfillment-detail article','receiving')]
        for path,ready,name in pages:
            page.goto(base+path);page.locator(ready).first.wait_for(state='attached')
            if name=='replenishment':
                page.locator('#load-run').click();page.locator('#run-items > .run-item').first.wait_for()
                assert 'OpenOrdersService' not in page.locator('body').inner_text()
                assert 'B03合成案例' not in page.locator('body').inner_text()
            if name=='order-detail': page.get_by_role('heading',name='本次決策紀錄',exact=True).wait_for()
            if name=='ordering':
                adjustment=page.locator('.product-row').first.locator('.adjustment-details')
                assert not adjustment.evaluate('element=>element.open')
                page.locator('.product-row').first.locator('[data-field=final_qty]').fill('6')
                assert adjustment.evaluate('element=>element.open')
            check(name)
        logout(page,base);login(page,base,'operator');check('operator-home')
        assert page.locator('.metric-card').first.locator('strong').inner_text()=='10'
        page.goto(base+'/headquarters/fulfillment');page.locator('#fulfillment-detail article').first.wait_for();check('headquarters')
        logout(page,base);login(page,base,'admin');check('admin-home')
        page.goto(base+'/admin');page.locator('.admin-row').first.wait_for();check('admin-products')
        page.get_by_role('button',name='帳號',exact=True).click();check('admin-users')
        assert page.locator('[data-password-toggle]').is_visible()
        page.get_by_role('button',name='門市商品政策',exact=True).click();page.locator('.admin-row').first.click();check('admin-policies')
        assert not errors,errors
        browser.close()
