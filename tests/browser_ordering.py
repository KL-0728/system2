"""Optional real Edge checks, run explicitly with pytest tests/browser_ordering.py.

Uses the existing isolated test transaction, not the developer's demo data.
Requires the local-only playwright package and installed Microsoft Edge.
"""
from pathlib import Path
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.testing.factories import make_run, make_order
from test_confirmation import _providers


def open_workbench(page, server):
    page.goto(server + '/login')
    page.locator('#username').fill('manager1')
    page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button', name='登入', exact=True).click()
    page.get_by_role('link', name='開始補貨', exact=True).click()
    page.locator('#intro-ack').check()
    page.get_by_role('button', name='確認並進入補貨').click()
    page.locator('#preview-button').wait_for()


@pytest.mark.parametrize('width', [320, 640])
def test_enlarged_text_alignment_preview_and_dialog(browser_server, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        open_workbench(page, browser_server)
        page.evaluate("document.documentElement.style.fontSize = '20px'")
        coat = page.locator('.product-row').filter(has=page.locator('[data-product-name]', has_text='雨衣'))
        positions = coat.evaluate('''row => {
            const text = row.querySelector('[data-item-action="restore"]');
            const range = document.createRange(); range.selectNodeContents(text);
            return [range.getBoundingClientRect().left,
                row.querySelector('.comparison').getBoundingClientRect().left];
        }''')
        assert abs(positions[0] - positions[1]) <= 2, positions
        coat.get_by_role('button', name='本次不訂', exact=True).click()
        dialog = page.locator('#exclude-dialog')
        assert dialog.is_visible()
        assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
        assert page.locator('#exclude-description .quantity-comparison strong').all_inner_texts() == ['30 件', '0 件']
        page.screenshot(path=f'instance/browser-check/dialog-large-text-{width}.png')
        page.locator('#exclude-cancel').click()
        coat.locator('[data-field="final_qty"]').fill('36')
        coat.locator('[data-field="reason_code"]').select_option('promotion')
        coat.locator('[data-field="reason"]').fill('活動商品說明' * 70)
        page.locator('#preview-button').click()
        page.locator('#stage-preview').wait_for(state='visible')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        for card in page.locator('.summary-card').all():
            assert card.evaluate('node => node.scrollWidth <= node.clientWidth')
        page.screenshot(path=f'instance/browser-check/preview-large-text-{width}.png', full_page=True)
        browser.close()


def test_save_locks_fields_and_reload_uses_newest_draft(browser_server):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()
        open_workbench(page, browser_server)
        drink = page.locator('.product-row').filter(has=page.locator('[data-product-name]', has_text='飲料'))
        drink.locator('[data-field="final_qty"]').fill('36')
        drink.locator('[data-field="reason_code"]').select_option('promotion')
        page.evaluate('''() => {
            const realFetch = window.fetch.bind(window);
            window.fetch = async (...args) => {
                if (args[1]?.method === 'PATCH') {
                    window.waitingSave = true;
                    await new Promise(resolve => { window.releaseSave = resolve; });
                }
                return realFetch(...args);
            };
        }''')
        page.locator('#save-button').click()
        page.wait_for_function('window.waitingSave === true')
        assert drink.locator('[data-field="final_qty"]').is_disabled()
        assert drink.locator('[data-field="reason_code"]').is_disabled()
        assert drink.locator('[data-item-action="exclude"]').is_disabled()
        page.evaluate('window.releaseSave()')
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
        assert drink.locator('[data-field="final_qty"]').is_enabled()
        other = context.new_page()
        other_drink = other.locator('.product-row').filter(has=other.locator('[data-product-name]', has_text='飲料'))
        # Open the saved draft in another tab, whose sessionStorage is independent.
        cached = page.evaluate('Object.values(sessionStorage).map(value => {try {return JSON.parse(value)} catch {return null}}).find(value => value?.draftId)')
        other.goto(page.url + ('&' if '?' in page.url else '?') + f"draft_id={cached['draftId']}")
        other.wait_for_function("document.querySelector('#draft-status').textContent.includes('已恢復')")
        other_drink.locator('[data-field="final_qty"]').fill('42')
        other_drink.locator('[data-field="reason_code"]').select_option('promotion')
        other.locator('#save-button').click()
        other.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
        page.reload()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('最新儲存內容')")
        assert drink.locator('[data-field="final_qty"]').input_value() == '42'
        page.locator('#preview-button').click()
        page.locator('#stage-preview').wait_for(state='visible')
        assert '312' in page.locator('#preview-total').inner_text()
        browser.close()


@pytest.fixture
def browser_server(seeded):
    _providers()
    seeded.config['MODULE_DEV'] = 'C'
    make_run(db.session)
    make_order(db.session)  # A newer D fixture must never be chosen by C.
    db.session.commit()
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize('width', [1440, 1280, 1024, 768, 390])
def test_real_browser_ordering_and_layout(browser_server, width):
    playwright = pytest.importorskip('playwright.sync_api')
    artifacts = Path('instance/browser-check')
    artifacts.mkdir(parents=True, exist_ok=True)
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': width, 'height': 900})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(browser_server + '/login')
        page.locator('#username').fill('manager1')
        page.locator('#password').fill('Synthetic-test-password-2026')
        page.get_by_role('button', name='登入', exact=True).click()
        page.get_by_role('link', name='開始補貨', exact=True).click()
        page.locator('#intro-ack').check()
        page.get_by_role('button', name='確認並進入補貨').click()
        page.locator('#preview-button').wait_for()
        assert page.locator('.product-row').count() == 10
        assert page.locator('[data-field="manual_ack"]').count() == 0
        page.screenshot(path=str(artifacts / f'workbench-{width}.png'), full_page=True)
        page.screenshot(path=str(artifacts / f'viewport-{width}.png'), full_page=False)
        page.locator('.product-row').first.screenshot(path=str(artifacts / f'product-{width}.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal page overflow'
        if width > 1000:
            first = page.locator('.product-row').first
            columns = first.locator(':scope > div')
            boxes = [columns.nth(index).bounding_box() for index in range(5)]
            assert max(box['y'] for box in boxes) - min(box['y'] for box in boxes) < 1
            for left, right in zip(boxes, boxes[1:]):
                assert left['x'] + left['width'] <= right['x']
            assert abs(first.locator('[data-field="reason_code"]').bounding_box()['y'] -
                       first.locator('[data-field="reason"]').bounding_box()['y']) < 1
        drink = page.locator('.product-row').filter(has=page.locator('[data-product-name]', has_text='飲料'))
        drink.locator('[data-field="final_qty"]').fill('36')
        drink.locator('[data-field="reason_code"]').select_option('promotion')
        page.get_by_role('button', name='只儲存草稿').click()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
        page.reload()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已恢復')")
        assert drink.locator('[data-field="final_qty"]').input_value() == '36'
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('#stage-preview').wait_for(state='visible')
        assert '306' in page.locator('#preview-total').inner_text()
        page.screenshot(path=str(artifacts / f'preview-{width}.png'), full_page=False)
        assert page.locator('[data-exception-product]').count() == 0
        page.get_by_role('button', name='确认數量並送出補貨單'.replace('确认', '確認')).click()
        page.wait_for_function("document.querySelector('#submit-error').textContent.includes('勾選')")
        page.locator('#order-ack').check()
        page.get_by_role('button', name='確認數量並送出補貨單').click()
        page.locator('#stage-result').wait_for(state='visible')
        page.get_by_role('link', name='查看訂單明細').click()
        page.get_by_role('heading', name='本次決策紀錄').wait_for()
        assert '36 件' in page.locator('#order-detail').inner_text()
        assert not errors, errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(artifacts / f'detail-{width}.png'), full_page=True)
        browser.close()


def test_mobile_exclusion_and_complete_special_demand(browser_server):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        page.goto(browser_server + '/login')
        page.locator('#username').fill('manager1')
        page.locator('#password').fill('Synthetic-test-password-2026')
        page.get_by_role('button', name='登入', exact=True).click()
        page.get_by_role('link', name='開始補貨', exact=True).click()
        page.locator('#intro-ack').check()
        page.get_by_role('button', name='確認並進入補貨').click()
        coat = page.locator('.product-row').filter(has=page.locator('[data-product-name]', has_text='雨衣'))
        coat.locator('[data-field="final_qty"]').fill('-1')
        coat.get_by_role('button', name='恢復建議量 30', exact=True).click()
        assert coat.locator('[data-field="final_qty"]').input_value() == '30'
        coat.locator('[data-field="final_qty"]').fill('120')
        coat.locator('[data-field="reason_code"]').select_option('local_demand')
        coat.locator('[data-field="reason"]').fill('下雨天')
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.wait_for_function("document.querySelector('#global-error').textContent.includes('雨衣') && document.querySelector('#global-error').textContent.includes('10')")
        assert '10' in coat.locator('[data-error-for="item"]').inner_text()
        coat.locator('[data-field="reason"]').fill('社區活動需要商品，已安排現場交付')
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('[data-exception="handling"]').select_option('exclude')
        page.locator('#exclude-dialog').wait_for(state='visible')
        assert coat.locator('[data-field="final_qty"]').input_value() == '120'
        page.locator('#exclude-cancel').click()
        assert coat.locator('[data-field="final_qty"]').input_value() == '120'
        page.locator('[data-exception="handling"]').select_option('exclude')
        page.locator('#exclude-confirm').click()
        page.locator('#stage-workbench').wait_for(state='visible')
        assert coat.locator('[data-field="final_qty"]').input_value() == '0'
        coat.get_by_role('button', name='恢復建議量 30', exact=True).click()
        assert coat.locator('[data-field="final_qty"]').input_value() == '30'
        coat.get_by_role('button', name='本次不訂', exact=True).click()
        page.locator('#exclude-confirm').click()
        assert coat.locator('[data-field="final_qty"]').input_value() == '0'
        assert coat.locator('[data-field="reason_code"]').input_value() == 'skip'
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('#stage-preview').wait_for(state='visible')
        assert '270' in page.locator('#preview-total').inner_text()
        assert '雨衣' in page.locator('#preview-excluded').inner_text()
        assert '調整原因：本次不訂' in page.locator('#preview-excluded').inner_text()
        assert page.locator('[data-exception-product]').count() == 0
        page.locator('#back-button').click()
        coat.locator('[data-field="final_qty"]').fill('1000')
        coat.locator('[data-field="reason_code"]').select_option('local_demand')
        coat.locator('summary').filter(has_text='特殊活動或團體需求').click()
        coat.locator('[data-field="need_date"]').fill('2026-10-10')
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.wait_for_function("document.querySelector('#global-error').textContent.includes('完整填寫')")
        coat.locator('[data-field="need_qty"]').fill('1000')
        coat.locator('[data-field="arrangement"]').fill('到貨後直接交付活動單位')
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('#stage-preview').wait_for(state='visible')
        assert '1270' in page.locator('#preview-total').inner_text()
        assert page.locator('[data-exception-product]').count() == 1
        page.locator('[data-exception="handling"]').select_option('special_arrangement')
        page.locator('[data-exception="ack"]').check()
        page.locator('#order-ack').check()
        page.get_by_role('button', name='確認數量並送出補貨單').click()
        page.locator('#stage-result').wait_for(state='visible')
        page.get_by_role('link', name='查看訂單明細').click()
        page.get_by_role('heading', name='本次決策紀錄').wait_for()
        assert '1000 件' in page.locator('#order-detail').inner_text()
        assert '到貨後直接交付活動單位' in page.locator('#order-detail').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()


def test_exclusion_dialog_cancel_escape_reason_and_logout(browser_server):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.goto(browser_server + '/login')
        page.locator('#username').fill('manager1')
        page.locator('#password').fill('Synthetic-test-password-2026')
        page.get_by_role('button', name='登入', exact=True).click()
        page.get_by_role('link', name='開始補貨', exact=True).click()
        page.locator('#intro-ack').check()
        page.get_by_role('button', name='確認並進入補貨').click()
        drink = page.locator('.product-row').filter(has=page.locator('[data-product-name]', has_text='飲料'))
        restore_note = '依本輪系統建議恢復訂購數量'
        drink.get_by_role('button', name='恢復建議量 30', exact=True).click()
        assert drink.locator('[data-field="reason"]').input_value() == restore_note
        page.get_by_role('button', name='只儲存草稿').click()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
        page.reload()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已恢復')")
        drink.get_by_role('button', name='本次不訂', exact=True).click()
        assert page.locator('#exclude-note').input_value() == ''
        page.locator('#exclude-cancel').click()
        assert drink.locator('[data-field="final_qty"]').input_value() == '30'
        assert drink.locator('[data-field="reason"]').input_value() == restore_note
        drink.get_by_role('button', name='本次不訂', exact=True).click()
        page.locator('#exclude-confirm').click()
        assert drink.locator('[data-field="reason"]').input_value() == ''
        drink.locator('[data-field="final_qty"]').fill('36')
        drink.locator('[data-field="reason_code"]').select_option('promotion')
        drink.locator('[data-field="reason"]').fill('原有說明')
        drink.get_by_role('button', name='恢復建議量 30', exact=True).click()
        assert drink.locator('[data-field="reason"]').input_value() == '原有說明'
        drink.locator('[data-field="final_qty"]').fill('36')
        drink.locator('[data-field="reason_code"]').select_option('promotion')
        drink.get_by_role('button', name='本次不訂', exact=True).click()
        assert '36' in page.locator('#exclude-description').inner_text()
        assert page.locator('#exclude-note').input_value() == '原有說明'
        page.screenshot(path='instance/browser-check/exclude-dialog.png')
        assert page.locator('#exclude-cancel').evaluate('(node) => node === document.activeElement')
        page.locator('#exclude-cancel').click()
        assert drink.locator('[data-field="final_qty"]').input_value() == '36'
        assert drink.locator('[data-field="reason_code"]').input_value() == 'promotion'
        drink.get_by_role('button', name='本次不訂', exact=True).click()
        page.keyboard.press('Escape')
        assert not page.locator('#exclude-dialog').is_visible()
        assert drink.locator('[data-field="final_qty"]').input_value() == '36'
        drink.get_by_role('button', name='本次不訂', exact=True).click()
        page.locator('#exclude-note').fill('')  # Named adjustment reason suffices for general exclusion.
        page.locator('#exclude-confirm').click()
        assert drink.locator('[data-field="final_qty"]').input_value() == '0'
        assert drink.locator('[data-field="reason_code"]').input_value() == 'skip'
        assert '本次不訂' in drink.locator('[data-item-state]').inner_text()
        page.get_by_role('button', name='只儲存草稿').click()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
        page.reload()
        page.wait_for_function("document.querySelector('#draft-status').textContent.includes('已恢復')")
        assert '本次不訂' in drink.locator('[data-item-state]').inner_text()
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('#stage-preview').wait_for(state='visible')
        page.locator('#order-ack').check()
        page.get_by_role('button', name='確認數量並送出補貨單').click()
        page.locator('#stage-result').wait_for(state='visible')
        page.get_by_role('link', name='查看訂單明細').click()
        page.get_by_role('heading', name='本次決策紀錄').wait_for()
        decision = page.locator('.summary-card').filter(has_text='飲料（本次排除）')
        assert '調整原因：本次不訂' in decision.inner_text()
        assert '一般補貨，未調整' not in decision.inner_text()
        page.get_by_role('button', name='登出', exact=True).click()
        page.wait_for_url('**/login')
        assert page.request.get(browser_server + '/api/auth/me').status == 401
        browser.close()


def test_network_unknown_refresh_recovers_original_order(browser_server):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        page.goto(browser_server + '/login')
        page.locator('#username').fill('manager1')
        page.locator('#password').fill('Synthetic-test-password-2026')
        page.get_by_role('button', name='登入', exact=True).click()
        page.get_by_role('link', name='開始補貨', exact=True).click()
        page.locator('#intro-ack').check()
        page.get_by_role('button', name='確認並進入補貨').click()
        page.get_by_role('button', name='儲存並預覽本單').click()
        page.locator('#stage-preview').wait_for(state='visible')
        page.locator('#order-ack').check()

        page.evaluate("""() => {
          const originalFetch = window.fetch;
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            if (String(args[0]).endsWith('/submit')) throw new TypeError('simulated response loss after backend success');
            return response;
          };
        }""")
        page.get_by_role('button', name='確認數量並送出補貨單').click()
        page.locator('#recovery-panel').wait_for(state='visible')
        assert page.locator('#back-button').is_disabled()
        assert page.locator('#submit-button').is_disabled()
        page.reload()
        page.locator('#stage-result').wait_for(state='visible')
        with page.expect_response('**/api/orders?*'):
            page.goto(browser_server + '/store/orders')
        page.locator('.order-card').wait_for()
        assert page.locator('.order-card').count() == 1
        browser.close()
