"""Run explicitly. Real Edge, real B services, isolated MySQL test transactions."""
from pathlib import Path
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import BusinessClock, Inventory, Store, User
from app.services.clock import business_now, utc_naive
from app.services.inventory import InventoryService
from datetime import timedelta
from app.contracts import InventoryMutation
from test_sales import csv_text


@pytest.fixture
def data_server(seeded):
    store = db.session.execute(db.select(Store).where(Store.code == 'DEMO1')).scalar_one()
    actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    inventories = db.session.execute(db.select(Inventory).where(Inventory.store_id == store.id)
        .order_by(Inventory.product_id)).scalars().all()
    b = business_now() + timedelta(days=1)
    db.session.get(BusinessClock, 1).business_anchor = utc_naive(b + timedelta(minutes=20))
    db.session.commit()
    case = dict(store=store, rows=inventories, b=b)
    text = csv_text(case, count=2)
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', text, case, actor
    finally:
        server.shutdown()
        thread.join(timeout=5)


def open_data(page, server):
    page.goto(server + '/login')
    page.locator('#username').fill('manager1')
    page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button', name='登入', exact=True).click()
    page.goto(server + '/store/data')
    page.locator('.stock-card').first.wait_for()


def upload(page, text):
    page.locator('#sales-file').set_input_files(dict(name='synthetic-sales.csv', mimeType='text/csv', buffer=text.encode('utf-8')))
    page.locator('#validate-sales').click()
    page.locator('#commit-sales').wait_for(state='visible')
    assert page.locator('#commit-sales').is_enabled()


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_csv_count_revisions_replays_and_mobile_layout(data_server, width):
    server, text, case, actor = data_server
    playwright = pytest.importorskip('playwright.sync_api')
    artifacts = Path('instance/browser-check')
    artifacts.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        open_data(page, server)
        upload(page, text)
        page.locator('#commit-sales').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('整批提交成功')")
        drink = page.locator('[data-sku="SKU01"]')
        assert '帳面總量 18' in drink.inner_text()
        page.locator('#repeat-sales').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('沒有再次入帳')")
        assert '帳面總量 18' in drink.inner_text()
        # Test input from another module, using the formal B writer; no D completion claim.
        row = db.session.get(Inventory, case['rows'][0].id)
        db.session.refresh(row)  # Browser requests committed in their own scoped session.
        InventoryService().apply_movement(mutation=InventoryMutation(case['store'].id, row.product_id,
            'receipt', 'browser-controlled-receipt', 10, 0, row.version, actor.id,
            case['b'] + timedelta(minutes=10), 'B02合成收貨輸入'), session=db.session)
        db.session.commit()
        page.locator('#refresh-status').click()
        page.wait_for_function("document.querySelector('[data-sku=SKU01]').textContent.includes('帳面總量 28')")
        page.locator('#count-physical').fill('20')
        page.locator('#count-reason').fill('B02實盤核對')
        page.locator('#submit-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('目前帳面 30件')")
        page.locator('#repeat-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('原盤點結果已確認')")
        assert '帳面總量 30' in drink.inner_text()
        page.locator('#count-physical').fill('21')
        page.locator('#count-reason').fill('修訂漏算一件')
        page.locator('#submit-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('目前帳面 31件')")
        assert 'H 31' in drink.inner_text()
        # Explicit wrong time reaches the server's cutoff rule.
        page.locator('#count-cutoff').fill('2026-10-09T20:30:00+08:00')
        page.locator('#submit-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('INVALID_COUNT_WINDOW')")
        assert '帳面總量 31' in drink.inner_text()
        page.evaluate("document.documentElement.style.fontSize = '20px'")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(artifacts / f'b02-data-{width}.png'), full_page=True)
        assert not errors, errors
        browser.close()


def test_lost_response_reload_retries_same_original_batch(data_server):
    server, text, _, _ = data_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        open_data(page, server)
        upload(page, text)
        page.evaluate("""() => {
          const original = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const result = await original(...args);
            if (String(args[0]).endsWith('/commit')) throw new TypeError('synthetic reply loss after success');
            return result;
          };
        }""")
        page.locator('#commit-sales').click()
        page.locator('#recovery').wait_for(state='visible')
        assert page.locator('#validate-sales').is_disabled()
        page.reload()
        page.locator('#recovery').wait_for(state='visible')
        page.locator('#retry-pending').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('原批次結果已確認')")
        assert '帳面總量 18' in page.locator('[data-sku="SKU01"]').inner_text()
        assert page.locator('#recovery').is_hidden()
        browser.close()


def test_invalid_whole_csv_and_changed_preview_invalidation(data_server):
    server, text, _, _ = data_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        open_data(page, server)
        bad = text.replace('SKU02', 'UNKNOWN')
        page.locator('#sales-file').set_input_files(dict(name='bad.csv', mimeType='text/csv', buffer=bad.encode('utf-8')))
        page.locator('#validate-sales').click()
        page.locator('#sales-errors li').wait_for()
        assert 'UNKNOWN_PRODUCT' in page.locator('#sales-errors').inner_text()
        assert page.locator('#commit-sales').is_disabled()
        assert '帳面總量 20' in page.locator('[data-sku="SKU01"]').inner_text()
        upload(page, text)
        page.locator('#sales-mode').select_option('historical')
        assert page.locator('#sales-preview').is_hidden()
        assert page.locator('#commit-sales').is_disabled()
        browser.close()


def test_history_daily_negative_and_covered_correction_on_screen(data_server):
    server, _, _, _ = data_server
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        open_data(page, server)
        text = page.request.get(server + '/store/data/sample.csv').text()
        page.locator('#sales-mode').select_option('historical')
        upload(page, text)
        with page.expect_response('**/api/sales/import/commit') as response:
            page.locator('#commit-sales').click()
        historical_id = response.value.json()['batch_id']
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('整批提交成功')")
        drink = page.locator('[data-sku="SKU01"]')
        assert '帳面總量 20' in drink.inner_text()
        assert 'H 不可用' in drink.inner_text()
        daily = text.replace('B02-2026-10-09,', 'B02-DAILY,')
        page.locator('#sales-mode').select_option('daily_posting')
        page.locator('#replacement-id').fill(str(historical_id))
        page.locator('#sales-reason').fill('明確轉日常')
        upload(page, daily)
        with page.expect_response('**/api/sales/import/commit') as response:
            page.locator('#commit-sales').click()
        daily_id = response.value.json()['batch_id']
        page.wait_for_function("document.querySelector('[data-sku=SKU01]').textContent.includes('H 18')")
        assert '帳面總量 -5' in page.locator('[data-sku="SKU02"]').inner_text()
        assert 'H 不可用' in page.locator('[data-sku="SKU02"]').inner_text()
        page.locator('#count-physical').fill('20')
        page.locator('#count-reason').fill('21:00核對')
        page.locator('#submit-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('盤點差額提交成功')")
        correction = daily.replace('B02-DAILY,', 'B02-CORRECT,').replace('SKU01,2026-10-09,2,', 'SKU01,2026-10-09,5,')
        page.locator('#replacement-id').fill(str(daily_id))
        page.locator('#sales-reason').fill('盤點涵蓋的銷售更正')
        upload(page, correction)
        page.locator('#commit-sales').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('整批提交成功')")
        assert '帳面總量 20' in drink.inner_text()
        assert 'H 不可用' in drink.inner_text()
        assert '已盤點涵蓋銷售更正' in drink.inner_text()
        page.locator('#count-physical').fill('20')
        page.locator('#count-reason').fill('重新核對實盤')
        page.locator('#submit-count').click()
        page.wait_for_function("document.querySelector('#data-message').textContent.includes('盤點差額提交成功')")
        assert 'H 20' in drink.inner_text()
        assert '已盤點涵蓋銷售更正' not in drink.inner_text()
        browser.close()
