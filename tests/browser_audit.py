"""Edge regression scenarios on isolated MySQL; pagination uses explicit read fixtures."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server


@pytest.fixture
def audit_server(seeded):
    Path('instance/browser-check').mkdir(parents=True, exist_ok=True)
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        thread.join(timeout=5)


def login(page, base, username):
    page.goto(base + '/login')
    page.locator('#username').fill(username)
    page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button', name='登入', exact=True).click()
    page.wait_for_url(base + '/')


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_password_visibility_login_retry_and_return_page(audit_server, width):
    playwright = pytest.importorskip('playwright.sync_api')
    base = audit_server
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_default_timeout(5000)
        page.goto(base + '/store/orders')
        page.wait_for_url(lambda url: str(url).startswith(base + '/login?next='))
        page.locator('#username').fill('manager1')
        page.locator('#password').fill('wrong-synthetic-password')
        toggle = page.locator('[data-password-toggle="password"]')
        assert page.locator('#password').get_attribute('type') == 'password'
        toggle.focus()
        page.keyboard.press('Enter')
        assert page.locator('#password').get_attribute('type') == 'text'
        assert toggle.get_attribute('aria-pressed') == 'true'
        assert page.locator('#password').input_value() == 'wrong-synthetic-password'
        page.get_by_role('button', name='隱藏密碼', exact=True).click()
        assert page.locator('#password').get_attribute('type') == 'password'
        page.get_by_role('button', name='登入', exact=True).click()
        page.get_by_role('alert').wait_for()
        assert '帳號或密碼錯誤' in page.get_by_role('alert').inner_text()
        assert page.locator('#username').input_value() == 'manager1'
        assert page.locator('#password').input_value() == ''
        assert page.locator('#password').get_attribute('type') == 'password'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        Path('instance/browser-check').mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f'instance/browser-check/audit-login-{width}.png', full_page=True)
        page.locator('#password').fill('Synthetic-test-password-2026')
        page.get_by_role('button', name='登入', exact=True).click()
        page.wait_for_url(base + '/store/orders')
        assert page.get_by_role('link', name='管理設定', exact=True).count() == 0
        browser.close()


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_admin_password_and_inflight_edit_lock(audit_server, width):
    playwright = pytest.importorskip('playwright.sync_api')
    base = audit_server
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_default_timeout(5000)
        login(page, base, 'admin')
        page.goto(base + '/admin')
        page.locator('.admin-row').first.wait_for()
        page.get_by_role('button', name='帳號', exact=True).click()
        page.locator('#admin-form [name=password]').fill('Never-submitted-synthetic-password')
        page.get_by_role('button', name='顯示密碼', exact=True).click()
        assert page.locator('#admin-password').get_attribute('type') == 'text'
        page.get_by_role('button', name='隱藏密碼', exact=True).click()
        assert page.locator('#admin-password').get_attribute('type') == 'password'
        page.get_by_role('button', name='商品', exact=True).click()
        page.locator('.admin-row').first.click()
        page.locator('#admin-form [name=name]').fill('儲存期間核對商品')
        page.evaluate('''() => {
            const original = window.fetch.bind(window);
            window.fetch = async (...args) => {
                if (args[0].startsWith('/api/admin/products/') && args[1]?.method === 'PATCH') {
                    window.savingProduct = true;
                    await new Promise(resolve => {window.finishProduct = resolve;});
                }
                return original(...args);
            };
        }''')
        page.get_by_role('button', name='儲存設定', exact=True).click()
        page.wait_for_function('window.savingProduct === true')
        assert page.get_by_role('button', name='帳號', exact=True).is_disabled()
        assert page.locator('#admin-form [name=name]').is_disabled()
        assert page.locator('.admin-row').first.is_disabled()
        page.evaluate('window.finishProduct()')
        page.wait_for_function("document.querySelector('#admin-status').textContent.includes('設定已儲存')")
        assert page.get_by_role('button', name='帳號', exact=True).is_enabled()
        page.locator('.admin-row').first.click()
        assert page.locator('#admin-form [name=name]').input_value() == '儲存期間核對商品'
        assert page.locator('#admin-form [name=sku]').is_disabled()
        page.get_by_role('button', name='帳號', exact=True).click()
        assert page.locator('#admin-password').get_attribute('type') == 'password'
        assert page.locator('#admin-password').input_value() == ''
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'instance/browser-check/audit-admin-{width}.png', full_page=True)
        browser.close()


def test_order_pagination_discards_late_responses(audit_server):
    playwright = pytest.importorskip('playwright.sync_api')
    base = audit_server
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page()
        page.set_default_timeout(5000)
        login(page, base, 'manager1')
        # Explicit read-only fixtures let responses arrive in a controlled order.
        page.add_init_script('''const originalAuditFetch = window.fetch.bind(window);
            window.fetch = async (...args) => {
                if (!args[0].startsWith('/api/orders?')) return originalAuditFetch(...args);
                const number = Number(new URL(args[0], location.origin).searchParams.get('page'));
                if (number === 3) {window.waitingThirdPage=true;await new Promise(resolve=>{window.releaseThirdPage=resolve;});}
                return new Response(JSON.stringify({orders:[{id:number,number:'READ-FIXTURE-'+number,
                    status:'SUBMITTED',submitted_at:'2026-10-08T13:00:00Z'}],page:number,total:80,has_next:number<4}),
                    {headers:{'Content-Type':'application/json'}});
            };''')
        page.goto(base + '/store/orders')
        page.wait_for_function("document.querySelector('#orders-list').textContent.includes('READ-FIXTURE-1')")
        page.locator('#next-page').click()
        page.wait_for_function("document.querySelector('#orders-list').textContent.includes('READ-FIXTURE-2')")
        page.locator('#next-page').click()
        page.wait_for_function('window.waitingThirdPage === true')
        page.locator('#previous-page').click()
        page.wait_for_function("document.querySelector('#orders-list').textContent.includes('READ-FIXTURE-1')")
        page.evaluate('window.releaseThirdPage()')
        page.wait_for_timeout(150)
        assert 'READ-FIXTURE-1' in page.locator('#orders-list').inner_text()
        assert '第 1 頁' in page.locator('#orders-pagination').inner_text()
        browser.close()
