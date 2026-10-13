"""Explicit real Edge tests: real B services, controlled D input, isolated MySQL."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import SalesDaily
from app.providers import register_provider
from app.testing.providers import ControlledOpenOrders
from test_replenishment import case

@pytest.fixture
def run_server(case,seeded):
    register_provider('open_orders',ControlledOpenOrders('pending'),test_only=True)
    # Third product intentionally lacks one recent date; other old days cannot fill it.
    row=db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id==case['store'].id,
        SalesDaily.product_id==case['stocks'][2].product_id,SalesDaily.business_date==case['b'].date())).scalar_one()
    db.session.delete(row); db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}',case
    finally: server.shutdown(); thread.join(timeout=5)

def open_runs(page,base):
    page.goto(base+'/login')
    page.locator('#username').fill('manager1'); page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button',name='登入',exact=True).click()
    page.goto(base+'/store/replenishment')
    page.wait_for_function("!document.querySelector('#generate-run').disabled")

@pytest.mark.parametrize('width',[1280,390,320])
def test_saved_run_curves_cycle_final_and_mobile(run_server,width):
    base,case=run_server
    from playwright.sync_api import sync_playwright
    artifacts=Path('instance/browser-check'); artifacts.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
        open_runs(page,base)
        assert '受控測試來源' in page.locator('#run-provider').inner_text()
        page.locator('#generate-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('補貨建議已保存')")
        drink=page.locator('[data-sku=SKU01]')
        assert '30件' in drink.inner_text() and drink.locator('[data-warning-code=PRE_ARRIVAL_STOCKOUT]').is_visible()
        missing=page.locator('[data-sku=SKU03]')
        assert '無有效建議' in missing.inner_text() and missing.locator('input').is_disabled()
        drink.locator('summary').filter(has_text='七日銷售').click()
        assert '2026-10-02' in drink.inner_text()
        drink.locator('summary').filter(has_text='已承諾＋待接單').click()
        assert 'controlled-1 U 12' in drink.inner_text()
        drink.locator('input').fill('31'); page.locator('#evaluate-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('試算完成')")
        assert drink.locator('[data-warning-code=INVALID_PACK]').is_visible() and drink.locator('input').input_value()=='31'
        page.locator('#run-cycle').select_option(str(case['cycles'][2].id))
        drink.locator('input').fill('1000'); page.locator('#evaluate-run').click()
        page.wait_for_function("document.querySelector('[data-sku=SKU01]').textContent.includes('供貨交期 3 天')")
        assert drink.locator('[data-warning-code=CAPACITY]').is_visible() and drink.locator('[data-warning-code=LARGE_QUANTITY]').is_visible()
        assert drink.locator('input').input_value()=='1000'
        page.locator('#load-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('已讀取當時建議')")
        assert '供貨交期 1 天' in drink.inner_text() and drink.locator('input').input_value()=='30'
        page.evaluate("document.documentElement.style.fontSize='20px'")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(artifacts/f'b03-run-{width}.png'),full_page=True)
        page.reload(); page.locator('#load-run').wait_for(); page.wait_for_function("!document.querySelector('#load-run').disabled")
        page.locator('#load-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('已讀取當時建議')")
        assert '30件' in page.locator('[data-sku=SKU01]').inner_text() and not errors
        browser.close()
