"""Real B calculation -> C confirmation in Edge; isolated MySQL, controlled D input."""
from pathlib import Path
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.testing.factories import make_run
from test_replenishment import case


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_home_preparation_ordering_and_shared_navigation(case, seeded, width):
    playwright = pytest.importorskip('playwright.sync_api')
    make_run(db.session, store_id=case['store'].id)
    db.session.commit()
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    artifacts = Path('instance/browser-check')
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with playwright.sync_playwright() as runner:
            browser = runner.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script("document.addEventListener('DOMContentLoaded', () => {document.documentElement.style.fontSize='20px';});")
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/login')
            page.locator('#username').fill('manager1')
            page.locator('#password').fill('Synthetic-test-password-2026')
            page.get_by_role('button', name='登入', exact=True).click()
            page.get_by_role('link', name='準備補貨建議', exact=True).wait_for(state='visible')
            assert page.get_by_role('link', name='準備補貨建議', exact=True).is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / f'review-home-{width}.png'), full_page=True)
            page.locator('.store-nav').get_by_role('link', name='資料管理', exact=True).click()
            page.wait_for_function("document.querySelectorAll('.stock-card').length === 10")
            assert page.locator('.store-nav [aria-current=page]').inner_text() == '資料管理'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('.store-nav').get_by_role('link', name='補貨', exact=True).click()
            page.get_by_role('link', name='準備補貨建議', exact=True).click()
            page.wait_for_function("!document.querySelector('#generate-run').disabled")
            assert page.locator('#saved-run option').count() == 0
            page.evaluate('''() => {
                const original = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    if (args[0] === '/api/replenishment/runs' && args[1]?.method === 'POST') {
                        window.waitingGenerate = true;
                        await new Promise(resolve => {window.releaseGenerate = resolve;});
                    }
                    return original(...args);
                };
            }''')
            page.locator('#generate-run').click()
            page.wait_for_function('window.waitingGenerate === true')
            assert page.locator('#forecast-options textarea').first.is_disabled()
            page.evaluate('window.releaseGenerate()')
            page.wait_for_function("document.querySelector('#run-message').textContent.includes('快照已保存')")
            assert page.locator('#saved-run option').count() == 1
            assert '可用現貨' in page.locator('#run-items').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / f'review-calculation-{width}.png'), full_page=True)
            page.get_by_role('link', name='使用最新建議訂購', exact=True).click()
            page.locator('#intro-ack').check()
            page.get_by_role('button', name='確認並進入補貨', exact=True).click()
            page.locator('#preview-button').wait_for()
            assert page.locator('.product-row').first.locator('[data-field="final_qty"]').input_value() == '42'
            page.locator('#preview-button').click()
            page.locator('#stage-preview').wait_for(state='visible')
            page.locator('#order-ack').check()
            page.locator('#submit-button').click()
            page.wait_for_function("document.querySelector('#submit-error').textContent.includes('重要例外')")
            for field in page.locator('[data-exception="handling"]').all():
                field.select_option('keep_and_contact')
            for field in page.locator('[data-exception="ack"]').all():
                field.check()
            page.locator('#submit-button').click()
            page.locator('#stage-result').wait_for(state='visible')
            page.get_by_role('link', name='查看訂單明細', exact=True).click()
            page.get_by_role('heading', name='本次決策紀錄', exact=True).wait_for()
            assert page.locator('.store-nav [aria-current=page]').inner_text() == '訂單'
            page.locator('.store-nav').get_by_role('link', name='訂單', exact=True).click()
            page.locator('.order-card').wait_for()
            assert '待統家接單' in page.locator('.order-card').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
