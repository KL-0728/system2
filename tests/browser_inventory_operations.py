"""B05 actual Edge: damaged operations, count-based reconciliation and lost replies."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import Inventory, InventoryReconciliation
from test_inventory import case, post_daily, move, advance
from browser_inventory import open_data

@pytest.fixture
def operations_server(case,seeded):
    post_daily(case,sold=0)
    move(case,physical=12,damaged=2,key='B05-browser-damaged')
    stocks=db.session.execute(db.select(Inventory).where(Inventory.store_id==case[1].id)
        .order_by(Inventory.product_id)).scalars().all()
    negative=(case[0],case[1],case[2],stocks[1],case[4])
    post_daily(negative,sold=25,key='B05-browser-negative')
    task=db.session.execute(db.select(InventoryReconciliation).where(
        InventoryReconciliation.product_id==stocks[1].product_id)).scalar_one()
    task_id=task.id
    advance(case[4]);db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',case,task_id
    finally:server.shutdown();thread.join(timeout=5)

def wait(page,text):
    page.wait_for_function("(text)=>document.querySelector('#data-message').textContent.includes(text)",arg=text)
    page.wait_for_function("!document.querySelector('#retry-pending').disabled")

def remove(page,qty,kind='disposal'):
    page.locator('#movement-kind').select_option(kind)
    page.locator('#movement-qty').fill(str(qty))
    page.locator('#movement-reason').fill('已核對損壞品數量並實際移出門市')
    page.locator('#submit-movement').click()

def count_task(page,task_id):
    page.locator('[data-reconciliation-id="'+str(task_id)+'"] button').click()
    page.locator('#count-physical').fill('10')
    page.locator('#count-unsellable').fill('0')
    page.locator('#count-reason').fill('日常銷售已入帳，重新核對有效21:00實盤')
    page.locator('#submit-count').click()

@pytest.mark.parametrize('width',[1280,390,320])
def test_disposal_return_reconciliation_history_and_mobile(operations_server,width):
    base,c,task_id=operations_server
    from playwright.sync_api import sync_playwright
    artifacts=Path('instance/browser-check');artifacts.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        open_data(page,base)
        page.wait_for_function("!document.querySelector('#submit-movement').disabled")
        drink=page.locator('.stock-card[data-sku=SKU01]')
        assert '帳面總量 32' in drink.inner_text() and 'H 30' in drink.inner_text()
        assert '負責角色：店長' in page.locator('#reconciliation-list').inner_text()
        assert '期限' in page.locator('#reconciliation-list').inner_text()
        remove(page,1);wait(page,'損壞品異動已入帳')
        assert '帳面總量 31' in drink.inner_text() and '不可販售 1' in drink.inner_text()
        page.locator('#repeat-movement').click();wait(page,'沒有再次扣庫存')
        assert '帳面總量 31' in drink.inner_text()
        remove(page,3,'return');wait(page,'INSUFFICIENT_DAMAGED_STOCK')
        assert '帳面總量 31' in drink.inner_text()
        remove(page,1,'return');wait(page,'損壞品異動已入帳')
        assert '帳面總量 30' in drink.inner_text() and '不可販售 0' in drink.inner_text()
        assert 'H 30' in drink.inner_text()
        assert 'receipt' in page.locator('#movement-list').inner_text()
        assert 'disposal' in page.locator('#movement-list').inner_text() and 'return' in page.locator('#movement-list').inner_text()
        rain=page.locator('.stock-card[data-sku=SKU02]')
        assert '帳面總量 -5' in rain.inner_text() and 'H 不可用' in rain.inner_text()
        count_task(page,task_id);wait(page,'盤點差額提交成功')
        assert 'H 10' in rain.inner_text()
        record=page.locator('[data-reconciliation-id="'+str(task_id)+'"]')
        assert '已處理' in record.inner_text() and '完成者id' in record.inner_text()
        record.locator('summary').click()
        assert 'revision_id' in record.inner_text()
        page.locator('#repeat-count').click();wait(page,'原盤點結果已確認')
        assert 'H 10' in rain.inner_text()
        page.evaluate("document.documentElement.style.fontSize='20px'")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(artifacts/f'b05-operations-{width}.png'),full_page=True)
        assert not errors
        browser.close()

@pytest.mark.parametrize('operation',['movement','reconciliation'])
def test_lost_reply_reload_and_original_request_recovery(operations_server,operation):
    base,c,task_id=operations_server
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':390,'height':900})
        open_data(page,base)
        page.wait_for_function("!document.querySelector('#submit-movement').disabled")
        path='**/api/inventory/disposals' if operation=='movement' else '**/api/inventory/reconciliations/*/resolve'
        def lose(route):
            response=route.fetch()
            assert response.status==201
            route.abort()
        page.route(path,lose,times=1)
        if operation=='movement':remove(page,1)
        else:count_task(page,task_id)
        wait(page,'提交結果尚未確認')
        assert page.locator('#recovery').is_visible() and page.locator('#submit-movement').is_disabled()
        page.reload()
        page.locator('#recovery').wait_for(state='visible')
        page.wait_for_function("!document.querySelector('#retry-pending').disabled")
        page.locator('#retry-pending').click()
        wait(page,'原異動已確認' if operation=='movement' else '原盤點結果已確認')
        assert page.locator('#recovery').is_hidden()
        card=page.locator('.stock-card[data-sku=SKU01]' if operation=='movement' else '.stock-card[data-sku=SKU02]')
        assert ('帳面總量 31' if operation=='movement' else 'H 10') in card.inner_text()
        browser.close()
