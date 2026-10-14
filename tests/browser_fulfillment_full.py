"""D's two-store browser acceptance flow on an isolated MySQL test transaction."""
from datetime import timedelta
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import BusinessClock, Inventory, Store
from app.testing.factories import make_order


@pytest.fixture
def two_store_server(seeded):
    seeded.config['MODULE_DEV'] = 'D'
    stores = {s.code: s for s in db.session.execute(db.select(Store).where(
        Store.code.in_(['DEMO1', 'DEMO2']))).scalars()}
    first, first_item = make_order(db.session, store_id=stores['DEMO1'].id, quantity=5)
    second, second_item = make_order(db.session, store_id=stores['DEMO2'].id, quantity=20)
    db.session.get(BusinessClock, 1).business_anchor += timedelta(minutes=1)
    db.session.commit()
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f'http://127.0.0.1:{server.server_port}',
            (first.id, first_item.id, first.store_id, first_item.product_id),
            (second.id, second_item.id, second.store_id, second_item.product_id))
    finally:
        server.shutdown()
        thread.join(timeout=5)


def login(page, base, username):
    page.goto(base + '/login')
    page.locator('#username').fill(username)
    page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button', name='登入', exact=True).click()
    page.wait_for_url(base + '/')
    assert page.request.get(base + '/api/auth/me').json()['username'] == username


def logout(page, base):
    page.get_by_role('button', name='登出', exact=True).click()
    page.wait_for_url(base + '/login')


def open_order(page, base, path, order_id):
    page.goto(base + path)
    target = page.request.get(base + f'/api/fulfillment/orders/{order_id}')
    assert target.status == 200
    store_id = target.json()['store_id']
    page.locator(f'#fulfillment-store option[value="{store_id}"]').wait_for(state='attached')
    page.locator('#fulfillment-store').select_option(str(store_id))
    page.locator(f'#fulfillment-order option[value="{order_id}"]').wait_for(state='attached')
    page.locator('#fulfillment-order').select_option(str(order_id))
    selected = page.locator('#fulfillment-order option:checked').inner_text()
    page.wait_for_function("label => document.querySelector('#fulfillment-detail > p')?.textContent.includes(label)", arg=selected)
    page.wait_for_function("id => document.querySelector('#fulfillment-detail').dataset.loadedOrderId === String(id)",arg=order_id)


def submit(page, title, fields=None, expected=200):
    form = page.locator('form').filter(has=page.get_by_role('button', name=title, exact=True)).first
    for name, value in (fields or {}).items():
        control = form.locator(f'[name="{name}"]')
        if control.evaluate('node => node.tagName') == 'SELECT':
            control.select_option(str(value))
        else:
            if name == 'eta' and control.get_attribute('type') == 'datetime-local':
                from datetime import datetime
                from zoneinfo import ZoneInfo
                value = datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Taipei')).replace(tzinfo=None).isoformat(timespec='minutes')
            control.fill(str(value))
    with page.expect_response(lambda r: r.request.method == 'POST' and '/api/fulfillment/' in r.url) as captured:
        form.get_by_role('button').click()
    response = captured.value
    assert response.status == expected, (title, response.status, response.text())
    if expected == 200:
        page.wait_for_timeout(200)
    return response.json()


def detail(page, base, order_id):
    response = page.request.get(base + f'/api/fulfillment/orders/{order_id}')
    assert response.status == 200
    return response.json()


def api_post(page, path, body):
    return page.evaluate('''async ({path, body}) => {
      const csrf = (await (await fetch('/api/auth/csrf')).json()).csrf_token;
      const orderId = document.querySelector('#fulfillment-order').value;
      const current = await (await fetch('/api/fulfillment/orders/' + orderId)).json();
      body.expected_version = current.version;
      const response = await fetch('/api/fulfillment/' + path, {method:'POST',
        headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify(body)});
      return {status:response.status, body:await response.json()};
    }''', {'path': path, 'body': body})


def stock(store_id, product_id):
    db.session.expire_all()
    row = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == store_id, Inventory.product_id == product_id)).scalar_one()
    return row.book_physical_qty, row.book_unsellable_qty


def test_damaged_replacement_and_disposal_in_edge(two_store_server):
    playwright = pytest.importorskip('playwright.sync_api')
    base, first, _ = two_store_server
    order_id, item_id, store_id, product_id = first
    assert stock(store_id, product_id) == (20, 0)
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, '完整接單')
        assert page.get_by_role('button', name='原訂出貨（非補送）').count() == 1
        submit(page, '原訂出貨（非補送）', {'quantity': 5})
        original = detail(page, base, order_id)['shipments'][0]
        assert original['lines'][0]['kind'] == 'original'
        logout(page, base)
        login(page, base, 'manager1')
        open_order(page, base, '/store/receiving', order_id)
        assert page.locator('form').filter(has=page.get_by_role('button', name='確認本批收貨')).first.locator('[name=note]').input_value() == ''
        submit(page, '確認本批收貨', {'checked_qty': 3, 'sellable_qty': 2,
            'damaged_qty': 1}, expected=400)
        assert stock(store_id, product_id) == (20, 0)
        submit(page, '確認本批收貨', {'note': '包裝破損'})
        assert stock(store_id, product_id) == (23, 1)
        variance = detail(page, base, order_id)['variances'][0]
        assert variance['kind'] == 'damaged' and variance['quantity'] == 1
        logout(page, base)
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, '授權補送', {'quantity_value': 1})
        assert page.get_by_role('button', name='補送出貨').count() == 1
        submit(page, '補送出貨', {'quantity': 1})
        result = detail(page, base, order_id)
        assert result['shipments'][1]['lines'][0]['kind'] == 'replacement'
        assert result['items'][0]['original_shipped_qty'] == 5
        logout(page, base)
        login(page, base, 'manager1')
        open_order(page, base, '/store/receiving', order_id)
        submit(page, '確認本批收貨', {'checked_qty': 1, 'sellable_qty': 1})
        assert stock(store_id, product_id) == (24, 1)
        submit(page, '損壞品處置', {'quantity_value': 1})
        assert stock(store_id, product_id) == (23, 0)
        assert api_post(page, f'variances/{variance["id"]}/damaged-removal',
            {'request_key': 'second-removal', 'quantity_value': 1,
             'action': 'discard'})['status'] == 409
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        browser.close()


def test_change_dispute_short_extra_tasks_and_access_in_edge(two_store_server):
    playwright = pytest.importorskip('playwright.sync_api')
    base, first, second = two_store_server
    first_id, _, _, _ = first
    order_id, item_id, store_id, product_id = second
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, '提出供貨變更', {'committed_qty': 15,
            'eta': '2026-10-10T21:00:00+08:00', 'reason': '供貨延後'})
        proposal = detail(page, base, order_id)
        assert proposal['items'][0]['status'] == 'CHANGE_PENDING'
        change_id = proposal['changes'][0]['id']
        logout(page, base)
        login(page, base, 'manager2')
        open_order(page, base, '/store/receiving', order_id)
        submit(page, '回覆提案')
        assert detail(page, base, order_id)['items'][0]['committed_qty'] == 15
        assert api_post(page, f'changes/{change_id}/response',
            {'accept': True, 'reason': ''})['status'] == 409
        submit(page, '提出取消未出貨量', {'reason': '需求調整'})
        logout(page, base)
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, '回覆提案', {'accept': 'no', 'reason': '已備貨'})
        assert api_post(page, f'orders/{order_id}/shipments', {
            'request_key': 'blocked-shipment', 'lines': [{'item_id': item_id,
                'quantity': 2, 'eta': '2026-10-10T21:00:00+08:00'}]})['status'] == 409
        submit(page, '重申原承諾')
        submit(page, '原訂出貨（非補送）', {'quantity': 2})
        line = detail(page, base, order_id)['shipments'][0]['lines'][0]
        logout(page, base)
        login(page, base, 'manager2')
        open_order(page, base, '/store/receiving', order_id)
        submit(page, '標記到貨待查', {'reason': '司機失聯'})
        assert detail(page, base, order_id)['shipments'][0]['lines'][0]['eta_disputed']
        logout(page, base)
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, '確認仍在途', {'eta': '2026-10-10T21:00:00+08:00',
            'reason': '司機已聯絡'})
        logout(page, base)
        login(page, base, 'manager2')
        open_order(page, base, '/store/receiving', order_id)
        submit(page, '確認本批收貨', {'checked_qty': 2, 'sellable_qty': 1,
            'short_qty': 1, 'note': '確認短收'})
        assert stock(store_id, product_id) == (21, 0)
        assert any(v['kind'] == 'short' for v in detail(page, base, order_id)['variances'])
        extra = page.locator('form').filter(has=page.get_by_role('button', name='登記隔離多送品'))
        extra.locator('[name=product_id]').select_option(index=1)
        submit(page, '登記隔離多送品', {'reason': '送錯商品'})
        held = next(e for e in detail(page, base, order_id)['timeline'] if e['type'] == 'EXTRA_HELD')
        submit(page, '新增聯絡待辦', {'reason': '請確認差異'})
        store_tasks = page.request.get(base + f'/api/fulfillment/tasks?store_id={store_id}').json()['tasks']
        assert any(t['task_type'] == 'contact_headquarters' for t in store_tasks)
        submit(page, '記錄聯絡結果', {'result': '統家已回覆'})
        store_tasks = page.request.get(base + f'/api/fulfillment/tasks?store_id={store_id}').json()['tasks']
        assert not any(t['task_type'] == 'contact_headquarters' and not t['completed_at'] for t in store_tasks)
        logout(page, base)
        login(page, base, 'operator')
        open_order(page, base, '/headquarters/fulfillment', order_id)
        submit(page, f'處理隔離多送品 {held["id"]}', {'reason': '退回統家'})
        assert any(e['type'] == 'EXTRA_RESOLVED' for e in detail(page, base, order_id)['timeline'])
        submit(page, '差異結案', {'reason': '短收已對帳'})
        assert all(v['status'] == 'CLOSED' for v in detail(page, base, order_id)['variances'])
        assert page.request.get(base + '/store/receiving').status == 403
        logout(page, base)
        login(page, base, 'manager1')
        assert page.request.get(base + f'/api/fulfillment/orders/{order_id}').status == 404
        assert page.request.get(base + '/headquarters/fulfillment').status == 403
        logout(page, base)
        assert page.request.get(base + f'/api/fulfillment/orders/{order_id}').status == 401
        assert not errors, errors
        browser.close()
