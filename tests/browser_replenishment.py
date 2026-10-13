"""Explicit real Edge tests: real B services, controlled D input, isolated MySQL."""
from pathlib import Path
from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from threading import Thread
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import SalesDaily, RunItem
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


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_decimal_metrics_round_only_on_screen(run_server, width):
    base, c = run_server
    # Real B calculation: 122 / 7; controlled D pending quantity remains 12.
    for row, quantity in zip(c['rows'], [18, 22, 20, 19, 21, 20, 2]):
        row.sold_qty = quantity
    zero_rows = db.session.execute(db.select(SalesDaily).where(
        SalesDaily.store_id == c['store'].id,
        SalesDaily.product_id == c['stocks'][1].product_id,
        SalesDaily.business_date.between(c['b'].date() - timedelta(days=6), c['b'].date())
    )).scalars().all()
    for row in zero_rows:
        row.sold_qty = 0
    db.session.commit()

    from playwright.sync_api import sync_playwright
    artifacts = Path('instance/browser-check')
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        open_runs(page, base)
        with page.expect_response(lambda response: response.url.endswith('/api/replenishment/runs')
                                  and response.request.method == 'POST') as generated:
            page.locator('#generate-run').click()
        payload = generated.value.json()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('補貨建議已保存')")
        item = next(item for item in payload['items'] if item['input_snapshot']['sku'] == 'SKU01')
        precision = {key: item[key] for key in ('mu', 'target_stock', 'raw_qty')}
        assert precision['mu'].startswith('17.428571')
        assert precision['target_stock'].startswith('44.857142')
        assert precision['raw_qty'].startswith('24.857142')
        saved = db.session.get(RunItem, item['run_item_id'])
        snapshot = deepcopy(saved.output_snapshot)
        assert {key: snapshot[key] for key in precision} == precision
        assert saved.mu == Decimal('17.428571428571')
        suggested = item['suggested_qty']
        assert suggested == 30

        def assert_metrics():
            card = page.locator('[data-sku=SKU01]')
            for label, expected in [('預估日銷量', '17.43'), ('目標庫存', '44.86'), ('整箱前需求', '24.86')]:
                assert card.locator('.run-metric').filter(has_text=label).locator('strong').inner_text() == expected
            assert card.locator('input').input_value() == str(suggested)
            assert page.locator('[data-sku=SKU02] .run-metric').filter(has_text='預估日銷量').locator('strong').inner_text() == '0.00'
            missing = page.locator('[data-sku=SKU03]')
            for label, expected in [('預估日銷量', '無有效預測'), ('目標庫存', '無法計算'), ('整箱前需求', '無法計算')]:
                assert missing.locator('.run-metric').filter(has_text=label).locator('strong').inner_text() == expected

        assert_metrics()
        page.screenshot(path=str(artifacts / f'b-display-{width}.png'), full_page=True)
        page.wait_for_function("!document.querySelector('#evaluate-run').disabled")
        page.locator('#evaluate-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('試算完成')")
        assert_metrics()
        page.locator('#load-run').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('已讀取當時建議')")
        assert_metrics()
        reread = page.evaluate("url => fetch(url).then(response => response.json())",
                              f"/api/replenishment/runs/{payload['run_id']}?store_id={c['store'].id}")
        reread_item = next(row for row in reread['items'] if row['run_item_id'] == item['run_item_id'])
        assert {key: reread_item[key] for key in precision} == precision
        assert reread_item['suggested_qty'] == suggested
        db.session.refresh(saved)
        assert saved.output_snapshot == snapshot
        assert saved.mu == Decimal('17.428571428571')

        # Decimal half rounding must work for a valid three-place manual forecast.
        page.locator('.forecast-choices > summary').click()
        manual = page.locator(f'[data-forecast-product="{c["stocks"][1].product_id}"]')
        manual.locator('summary').click()
        manual.locator('[data-field=mode]').select_option('manual')
        manual.locator('[data-field=daily-demand]').fill('5.135')
        manual.locator('[data-field=manual-reason]').fill('已核對每日活動需求，保留三位小數進行計算')
        manual.locator('[data-action=save-manual]').click()
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('人工預測已保存')")
        page.wait_for_function("!document.querySelector('#generate-run').disabled")
        manual.locator('[data-field=confirmed]').check()
        with page.expect_response(lambda response: response.url.endswith('/api/replenishment/runs')
                                  and response.request.method == 'POST') as manual_run:
            page.locator('#generate-run').click()
        manual_item = next(row for row in manual_run.value.json()['items'] if row['input_snapshot']['sku'] == 'SKU02')
        page.wait_for_function("document.querySelector('#run-message').textContent.includes('補貨建議已保存')")
        assert Decimal(manual_item['mu']) == Decimal('5.135')
        assert page.locator('[data-sku=SKU02] .run-metric').filter(has_text='預估日銷量').locator('strong').inner_text() == '5.14'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        browser.close()
