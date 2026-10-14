"""Edge desktop/mobile: admin maintenance and actual B/C/D ordering loop."""
from pathlib import Path
from threading import Thread
from datetime import timedelta
import os
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import User, DeliveryCycle, Inventory, BusinessClock
from app.services.replenishment import ReplenishmentService
from browser_fulfillment_full import login, logout, submit, stock


@pytest.fixture
def real_server(seeded):
    manager=db.session.execute(db.select(User).where(User.username=='manager1')).scalar_one()
    store_id=manager.stores[0].id
    cycle=db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==store_id)
        .order_by(DeliveryCycle.arrival_at)).scalars().first()
    run=ReplenishmentService().generate(store_id=store_id,actor_id=manager.id,cycle_id=cycle.id,
        expected_version=manager.stores[0].calculation_version,session=db.session)
    product_id=run.items[0].product_id
    db.session.get(BusinessClock,1).business_anchor+=timedelta(minutes=1)
    db.session.commit()
    assert all(not row[1] for row in seeded.extensions['service_providers'].values())
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}',store_id,product_id
    finally: server.shutdown();thread.join(timeout=5)


@pytest.mark.parametrize('width',[1280,390,320])
def test_admin_management_in_edge(real_server,width):
    playwright=pytest.importorskip('playwright.sync_api')
    base,store_id,product_id=real_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        login(page,base,'admin');page.get_by_role('link',name='管理設定',exact=True).click()
        page.locator('.admin-row').first.wait_for()
        page.locator('.admin-row').first.click()
        page.locator('#admin-form [name=name]').fill('飲料（管理修改）')
        page.get_by_role('button',name='儲存設定',exact=True).click()
        page.wait_for_function("document.querySelector('#admin-status').textContent.includes('設定已儲存')")
        page.get_by_role('button',name='門市商品政策',exact=True).click()
        page.locator('.admin-row').first.click()
        page.locator('#admin-form [name=safety_stock]').fill('15')
        with page.expect_response(lambda r:'/api/admin/policies/' in r.url and r.request.method=='PATCH') as saved:
            page.get_by_role('button',name='儲存設定',exact=True).click()
        assert saved.value.status==200
        page.locator('.admin-row').filter(has_text='政策 v2').first.wait_for()
        page.locator('#audit-filter [name=action]').fill('management.policies.save')
        page.get_by_role('button',name='查詢紀錄',exact=True).click()
        page.locator('#audit-list details').first.wait_for()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        Path('instance/browser-check').mkdir(parents=True,exist_ok=True)
        page.screenshot(path=f'instance/browser-check/admin-{width}.png',full_page=True)
        assert not errors,errors
        browser.close()


@pytest.mark.parametrize('width',[1280,390])
def test_real_three_stage_order_and_receipt_in_edge(real_server,width):
    playwright=pytest.importorskip('playwright.sync_api')
    base,store_id,product_id=real_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        login(page,base,'manager1')
        page.get_by_role('link',name='開始補貨',exact=True).click()
        page.locator('#intro-ack').check();page.get_by_role('button',name='確認並進入補貨',exact=True).click()
        page.locator('#preview-button').wait_for()
        assert page.locator('.product-row').count()==10
        page.locator('#preview-button').click();page.locator('#stage-preview').wait_for(state='visible')
        page.locator('#order-ack').check()
        with page.expect_response(lambda r:r.url.endswith('/submit') and r.request.method=='POST') as submitted:
            page.locator('#submit-button').click()
        assert submitted.value.status==201,submitted.value.text()
        order_id=submitted.value.json()['order_id']
        page.locator('#result-content').wait_for(state='visible')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        logout(page,base);login(page,base,'operator')
        page.get_by_role('link',name='前往接單履約',exact=True).click()
        page.locator('#fulfillment-order').select_option(str(order_id))
        page.get_by_role('button',name='完整接單',exact=True).first.wait_for()
        submit(page,'完整接單')
        submit(page,'原訂出貨（非補送）',{'quantity':30})
        logout(page,base);login(page,base,'manager1')
        page.get_by_role('link',name='收貨',exact=True).click()
        page.locator('#fulfillment-order').select_option(str(order_id))
        page.get_by_role('button',name='確認本批收貨',exact=True).first.wait_for()
        submit(page,'確認本批收貨',{'checked_qty':30,'sellable_qty':30,'damaged_qty':0,'short_qty':0})
        assert stock(store_id,product_id)==(50,0)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'instance/browser-check/real-loop-{width}.png',full_page=True)
        page.goto(f'{base}/store/orders/{order_id}?store_id={store_id}')
        page.get_by_role('heading', name='供貨狀態', exact=True).wait_for()
        assert '已收可售' in page.locator('#order-detail').inner_text()
        assert '核對收貨' in page.locator('#order-detail').inner_text()
        assert '部分供貨' in page.locator('#order-detail').inner_text() or '部分收貨' in page.locator('#order-detail').inner_text() or '已收貨' in page.locator('#order-detail').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        browser.close()
