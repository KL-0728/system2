"""Real writes with deliberately lost HTTP responses; isolated MySQL only."""
from threading import Thread
from pathlib import Path
import os
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import User, ShipmentItem, OrderItem
from app.services.fulfillment import fulfillment_service as service
from test_full_integration import real_order
from browser_fulfillment_full import login, open_order, stock, submit


@pytest.fixture
def prepared_server(seeded, client, request):
    order, item, manager, cycle, run = real_order(seeded, client)
    operator = db.session.execute(db.select(User).where(User.username == 'operator')).scalar_one()
    eta = cycle.arrival_at.replace(tzinfo=run.baseline_at.tzinfo).isoformat()
    service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30, eta=eta, session=db.session)
    case = request.param
    shipment = None
    if case in ('batch','ship_many'):
        second = db.session.execute(db.select(OrderItem).where(OrderItem.order_id == order.id,
            OrderItem.id != item.id).order_by(OrderItem.id)).scalars().first()
        service.accept(item_id=second.id, actor_id=operator.id, committed_qty=second.original_qty, eta=eta, session=db.session)
        if case == 'batch':
            shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='prepare',
                lines=[dict(item_id=i.id, quantity=i.original_qty, eta=eta) for i in (item,second)], session=db.session)
    elif case != 'ship':
        shipment = service.ship(order_id=order.id, actor_id=operator.id, request_key='prepare',
            lines=[dict(item_id=item.id, quantity=30, eta=eta)], session=db.session)
    if case in ('authorize', 'remove'):
        line = db.session.execute(db.select(ShipmentItem).where(ShipmentItem.shipment_id == shipment.id)).scalar_one()
        service.receive(shipment_id=shipment.id, actor_id=manager.id, request_key='prepare-receipt',
            lines=[dict(shipment_item_id=line.id, checked_qty=30, sellable_qty=28, damaged_qty=2, short_qty=0, note='破損隔離')], session=db.session)
    db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', order.id, order.store_id, item.product_id, case
    finally: server.shutdown();thread.join(timeout=5)


@pytest.mark.parametrize('prepared_server',['ship','receive','authorize','remove','extra','batch','unknown'],indirect=True)
def test_lost_write_response_reload_original_retry(prepared_server):
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    configs={'ship':('operator','原訂出貨（非補送）','shipments',{'quantity':'30'}),
        'receive':('manager1','確認本批收貨','receipts',{}),
        'authorize':('operator','授權補送','authorizations',{}),
        'remove':('manager1','損壞品處置','damaged-removal',{}),
        'extra':('manager1','登記隔離多送品','extra',{}),
        'batch':('manager1','整批正常收貨','receipts',{}),
        'unknown':('manager1','標記到貨待查','unknown',{'reason':'未依時間到貨，請查明'})}
    username,title,suffix,fields=configs[case]
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':320,'height':900})
        baseline_js=os.getenv('HARDENING_BASELINE_JS')
        if baseline_js:page.route('**/static/js/fulfillment.js*',lambda route:route.fulfill(path=baseline_js,content_type='application/javascript'))
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        login(page,base,username)
        open_order(page,base,'/headquarters/fulfillment' if username=='operator' else '/store/receiving',order_id)
        form=page.locator('form').filter(has=page.get_by_role('button',name=title,exact=True)).first
        for name,value in fields.items():form.locator(f'[name={name}]').fill(value)
        if case=='extra': form.locator('[name=reason]').fill('額外到貨先隔離')
        if case=='batch':
            assert stock(store_id,product_id)==(20,0)
            form.get_by_role('button',name=title,exact=True).click()
            assert stock(store_id,product_id)==(20,0)
            form.locator('[name=confirmed]').check()
        observed={}
        def lose(route):
            if route.request.method!='POST':return route.continue_()
            response=route.fetch();assert response.status==200,response.text()
            observed['id']=response.json()['id'];observed['payload']=route.request.post_data_json
            route.abort('failed')
        page.route(f'**/{suffix}',lose)
        form.get_by_role('button',name=title,exact=True).click()
        page.get_by_role('button',name='以原內容重試',exact=True).wait_for(timeout=5000)
        assert page.locator('#fulfillment-store').is_disabled()
        assert page.locator('#fulfillment-order').is_disabled()
        saved=page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('system2-fulfillment:'))))")
        assert saved['body']==observed['payload']
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        before=stock(store_id,product_id)
        page.unroute(f'**/{suffix}',lose)
        page.reload()
        page.get_by_role('button',name='以原內容重試',exact=True).wait_for(timeout=5000)
        assert page.locator('#fulfillment-order').is_disabled()
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/'+suffix)) as retried:
            page.get_by_role('button',name='以原內容重試',exact=True).click()
        assert retried.value.status==200,retried.value.text()
        assert retried.value.json()['id']==observed['id']
        page.wait_for_function("!document.querySelector('#fulfillment-order').disabled")
        assert stock(store_id,product_id)==before
        assert not page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:'))")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors,errors
        Path('instance/browser-check').mkdir(parents=True,exist_ok=True)
        page.screenshot(path=f'instance/browser-check/hardening-{case}-320.png',full_page=True)
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
def test_deep_link_loads_real_order_when_current_list_has_no_match(prepared_server):
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page()
        login(page,base,'operator')
        def empty_current_list(route):
            # Real filtered HTTP result; no fabricated order/detail payload.
            from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
            parts=urlsplit(route.request.url)
            query=dict(parse_qsl(parts.query));query['number']='OFF-PAGE-CONTROLLED-READ'
            response=route.fetch(url=urlunsplit(parts._replace(query=urlencode(query))))
            assert response.status==200 and response.json()['orders']==[]
            route.fulfill(response=response)
        page.route('**/api/fulfillment/orders?*',empty_current_list)
        page.goto(f'{base}/headquarters/fulfillment?store_id={store_id}&order_id={order_id}')
        page.wait_for_function("id=>document.querySelector('#fulfillment-detail').dataset.loadedOrderId===String(id)",arg=order_id)
        assert page.locator('#fulfillment-store').input_value()==str(store_id)
        assert page.locator('#fulfillment-order').input_value()==str(order_id)
        assert page.get_by_role('button',name='原訂出貨（非補送）',exact=True).count()==1
        page.unroute('**/api/fulfillment/orders?*',empty_current_list)
        page.locator('#order-filters [name=number]').fill('NO-MATCH-AFTER-DEEP-LINK')
        page.get_by_role('button',name='搜尋訂單',exact=True).click()
        page.wait_for_function("document.querySelector('#fulfillment-detail').textContent.includes('目前沒有正式訂單')")
        assert page.locator('#fulfillment-order option').count()==0
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
def test_full_real_order_multi_item_shipping_and_receiving_in_browser(prepared_server):
    from browser_fulfillment_full import detail,logout
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':390,'height':900})
        login(page,base,'operator');open_order(page,base,'/headquarters/fulfillment',order_id)
        while (remaining:=page.get_by_role('button',name='完整接單',exact=True).count()):
            submit(page,'完整接單')
            page.wait_for_function("n=>Array.from(document.querySelectorAll('button')).filter(b=>b.textContent==='完整接單').length<n",arg=remaining)
        form=page.locator('form').filter(has=page.get_by_role('button',name='整單原訂出貨（依承諾日期）',exact=True)).first
        assert form.locator('input[type=number]').count()==10
        form.get_by_role('button').click()
        assert detail(page,base,order_id)['shipments']==[]
        form.locator('[name=confirmed]').focus();page.keyboard.press('Space');page.keyboard.press('Tab')
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/shipments')) as shipped:
            page.keyboard.press('Enter')
        assert shipped.value.status==200,shipped.value.text()
        batch=detail(page,base,order_id)['shipments'][0]
        assert len(batch['lines'])==10 and all(l['shipped_qty']==30 for l in batch['lines'])
        logout(page,base);login(page,base,'manager1');open_order(page,base,'/store/receiving',order_id)
        receipt=page.locator('form').filter(has=page.get_by_role('button',name='整批正常收貨',exact=True)).first
        receipt.get_by_role('button').click()
        assert stock(store_id,product_id)==(20,0)
        receipt.locator('[name=confirmed]').focus();page.keyboard.press('Space');page.keyboard.press('Tab')
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/receipts')) as received:
            page.keyboard.press('Enter')
        assert received.value.status==200,received.value.text()
        page.wait_for_function("document.querySelector('#fulfillment-detail').textContent.includes('待核對 0')")
        current=detail(page,base,order_id)
        assert all(i['status']=='RECEIVED' for i in current['items'])
        assert '已收貨' in page.locator('#fulfillment-order option:checked').inner_text()
        assert all(l['checked_qty']==30 for l in current['shipments'][0]['lines'])
        assert not [t for t in current['tasks'] if not t['completed_at']]
        assert stock(store_id,product_id)==(50,0)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path='instance/browser-check/hardening-real-batch-390.png',full_page=True)
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path='instance/browser-check/hardening-real-batch-390-viewport.png')
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
@pytest.mark.parametrize('width',[1280,390,320])
def test_late_eta_labels_keyboard_and_error_recovery(prepared_server,width):
    from datetime import datetime,timedelta
    from browser_fulfillment_full import detail
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        login(page,base,'operator');open_order(page,base,'/headquarters/fulfillment',order_id)
        promised=detail(page,base,order_id)['items'][0]['eta']
        form=page.locator('form').filter(has=page.get_by_role('button',name='原訂出貨（非補送）',exact=True)).first
        eta=form.get_by_label('物流預估到貨（台北）',exact=True)
        assert eta.get_attribute('type')=='datetime-local'
        later=(datetime.fromisoformat(eta.input_value())+timedelta(hours=2)).isoformat(timespec='minutes')
        submit(page,'原訂出貨（非補送）',{'quantity':30,'eta':later+'+08:00'},expected=422)
        reason=form.get_by_label('晚於承諾時填延遲原因',exact=True)
        assert reason.is_enabled() and page.locator('#fulfillment-store').is_enabled()
        reason.fill('配送車輛故障，保留原承諾並查明延誤')
        reason.press('Tab')
        assert form.get_by_role('button',name='原訂出貨（非補送）',exact=True).evaluate('el=>el===document.activeElement')
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/shipments')) as written:
            page.keyboard.press('Enter')
        assert written.value.status==200,written.value.text()
        current=detail(page,base,order_id)
        assert current['items'][0]['eta']==promised
        assert current['shipments'][0]['lines'][0]['eta_disputed']
        assert any(t['task_type']=='investigate_shipment' and not t['completed_at'] for t in current['tasks'])
        page.wait_for_function("document.querySelector('#fulfillment-detail').textContent.includes('到貨待查')")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=f'instance/browser-check/hardening-late-{width}.png',full_page=True)
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=f'instance/browser-check/hardening-late-{width}-viewport.png')
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
def test_write_success_read_failure_is_reported_as_success(prepared_server):
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page(viewport={'width':390,'height':900})
        login(page,base,'operator');open_order(page,base,'/headquarters/fulfillment',order_id)
        written=False
        def intercept(route):
            nonlocal written
            if route.request.method=='POST':
                response=route.fetch();assert response.status==200
                written=True;route.fulfill(response=response)
            elif written:route.abort('failed')
            else:route.continue_()
        page.route(f'**/api/fulfillment/orders/{order_id}**',intercept)
        form=page.locator('form').filter(has=page.get_by_role('button',name='原訂出貨（非補送）',exact=True)).first
        form.locator('[name=quantity]').fill('30')
        form.get_by_role('button',name='原訂出貨（非補送）',exact=True).click()
        page.wait_for_function("document.querySelector('#fulfillment-status').textContent.includes('操作已完成，更新畫面失敗')")
        assert not page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:'))")
        assert not page.locator('#fulfillment-store').is_disabled()
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
def test_another_tab_record_cannot_replace_original_unknown_request(prepared_server):
    from browser_fulfillment_full import detail
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page()
        login(page,base,'operator');open_order(page,base,'/headquarters/fulfillment',order_id)
        def lose(route):
            response=route.fetch();assert response.status==200
            route.abort('failed')
        page.route('**/shipments',lose)
        form=page.locator('form').filter(has=page.get_by_role('button',name='原訂出貨（非補送）',exact=True)).first
        form.locator('[name=quantity]').fill('30');form.get_by_role('button').click()
        page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
        original=page.evaluate("Object.entries(localStorage).find(([k])=>k.startsWith('system2-fulfillment:'))")
        # Controlled undelivered request, separate from the real successful write.
        page.evaluate('''([originalKey, raw])=>{
            const other=JSON.parse(raw);other.body.request_key='controlled-undelivered-other-tab';
            const otherKey=originalKey.slice(0,originalKey.lastIndexOf(':'))+':controlled-other-tab';
            localStorage.setItem(otherKey,JSON.stringify(other));
            dispatchEvent(new StorageEvent('storage',{key:otherKey,newValue:JSON.stringify(other)}));
        }''',original)
        assert page.evaluate('(key)=>localStorage.getItem(key)',original[0])==original[1]
        assert page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('system2-fulfillment:')).length")==2
        page.unroute('**/shipments',lose);page.reload()
        for _ in range(2):
            page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
            with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/shipments')) as replay:
                page.get_by_role('button',name='以原內容重試',exact=True).click()
            assert replay.value.status in (200,409),replay.value.text()
            if replay.value.status==409:assert replay.value.json()['error']['code']=='VERSION_CONFLICT'
        page.wait_for_function("!document.querySelector('#fulfillment-order').disabled")
        assert not page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:'))")
        assert len(detail(page,base,order_id)['shipments'])==1
        browser.close()


@pytest.mark.parametrize('prepared_server',['ship'],indirect=True)
def test_pending_other_tab_discovered_after_success_keeps_controls_locked(prepared_server):
    playwright=pytest.importorskip('playwright.sync_api')
    base,order_id,store_id,product_id,case=prepared_server
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        page=browser.new_page()
        login(page,base,'operator');open_order(page,base,'/headquarters/fulfillment',order_id)
        def save_other_and_succeed(route):
            response=route.fetch();assert response.status==200
            page.evaluate('''()=>{
                const [savedKey,raw]=Object.entries(localStorage).find(([k])=>k.startsWith('system2-fulfillment:'));
                const other=JSON.parse(raw);other.body.request_key='controlled-undelivered-during-write';
                const otherKey=savedKey.slice(0,savedKey.lastIndexOf(':'))+':controlled-during-write';
                localStorage.setItem(otherKey,JSON.stringify(other));
                dispatchEvent(new StorageEvent('storage',{key:otherKey,newValue:JSON.stringify(other)}));
            }''')
            route.fulfill(response=response)
        page.route('**/shipments',save_other_and_succeed)
        form=page.locator('form').filter(has=page.get_by_role('button',name='原訂出貨（非補送）',exact=True)).first
        form.locator('[name=quantity]').fill('30');form.get_by_role('button').click()
        page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
        assert page.locator('#fulfillment-store').is_disabled()
        assert page.locator('#fulfillment-order').is_disabled()
        browser.close()
