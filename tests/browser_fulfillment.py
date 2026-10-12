"""Real Edge smoke test for the D fulfillment and receiving screens."""
from datetime import timedelta
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app.extensions import db
from app.models import BusinessClock, Inventory
from app.testing.factories import make_order


@pytest.fixture
def fulfillment_server(seeded):
    seeded.config['MODULE_DEV'] = 'D'
    order, item = make_order(db.session, quantity=5)
    clock = db.session.get(BusinessClock, 1)
    clock.business_anchor += timedelta(minutes=1)
    db.session.commit()
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', order.id, order.store_id, item.product_id
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _login(page, base, username):
    page.goto(base + '/login')
    page.locator('#username').fill(username)
    page.locator('#password').fill('Synthetic-test-password-2026')
    page.get_by_role('button', name='登入', exact=True).click()


@pytest.mark.parametrize('width', [390, 1280])
def test_accept_ship_and_partial_receive_in_edge(fulfillment_server, width):
    playwright = pytest.importorskip('playwright.sync_api')
    base, order_id, store_id, product_id = fulfillment_server
    stock = db.session.execute(db.select(Inventory).where(
        Inventory.store_id == store_id, Inventory.product_id == product_id)).scalar_one()
    before = stock.book_physical_qty
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        _login(page, base, 'operator')
        page.goto(base + '/headquarters/fulfillment')
        page.locator('#fulfillment-order').select_option(str(order_id))
        page.locator('form').filter(has=page.get_by_role('button', name='完整接單')).get_by_role('button').click()
        page.get_by_text('承諾 5 件').wait_for()
        shipping = page.locator('form').filter(has=page.get_by_role('button', name='原訂出貨（非補送）', exact=True))
        shipping.locator('[name=quantity]').fill('5')
        shipping.get_by_role('button').click()
        page.get_by_text('待核對 5').wait_for()
        assert not errors, errors
        page.get_by_role('button', name='登出', exact=True).click()
        _login(page, base, 'manager1')
        page.goto(base + '/store/receiving')
        page.locator('#fulfillment-order').select_option(str(order_id))
        receiving = page.locator('form').filter(has=page.get_by_role('button', name='確認本批收貨')).first
        receiving.locator('[name=checked_qty]').fill('2')
        receiving.locator('[name=sellable_qty]').fill('2')
        receiving.get_by_role('button').click()
        page.get_by_text('已核對 2 · 待核對 3').wait_for()
        assert page.locator('#fulfillment-error').inner_text() == ''
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors, errors
        browser.close()
    db.session.expire_all()
    assert db.session.get(Inventory, stock.id).book_physical_qty == before + 2
