"""Browser recovery paths backed by real B/C/D and isolated MySQL data."""
from threading import Thread
import os
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import Product, OrderDraft, User, Store, DeliveryCycle, Order, Shipment, OrderItem, Inventory
from app.services.clock import aware
from app.services.fulfillment import fulfillment_service as service
from app.services.orders import ordering_service
from app.services.replenishment import ReplenishmentService
from test_system_hardening import setup_order
from test_six_review import new_draft
from test_submission import _write, _preview, _submit_body
from conftest import login as api_login
from browser_fulfillment_full import login, open_order


@pytest.fixture
def review_server(seeded, client):
    order, item, manager, cycle, run, operator, admin = setup_order(seeded, client)
    service.accept(item_id=item.id, actor_id=operator.id, committed_qty=30,
        eta=aware(cycle.arrival_at).isoformat(), session=db.session)
    draft = new_draft(order, manager, cycle)
    ReplenishmentService().generate(store_id=order.store_id, actor_id=manager.id, cycle_id=cycle.id,
        expected_version=manager.stores[0].calculation_version, session=db.session)
    second_manager = db.session.execute(db.select(User).where(User.username=='manager2')).scalar_one()
    second_store = second_manager.stores[0]
    second_cycle = db.session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id==second_store.id)
        .order_by(DeliveryCycle.arrival_at)).scalars().first()
    second_run = ReplenishmentService().generate(store_id=second_store.id, actor_id=second_manager.id,
        cycle_id=second_cycle.id, expected_version=second_store.calculation_version, session=db.session)
    db.session.commit()
    assert api_login(client, 'manager2').status_code==200
    assert _write(client,'POST','/api/ordering/acknowledgement',{'acknowledged':True}).status_code==200
    second_draft = ordering_service.create_draft(second_manager, store_id=second_store.id,
        run_id=second_run.run_id, cycle_id=second_cycle.id)
    db.session.commit()
    preview=_preview(client, second_draft)
    response=_write(client,'POST',f"/api/order-drafts/{second_draft['id']}/submit", _submit_body(second_draft,preview), {'Idempotency-Key':'second-real-order'})
    assert response.status_code==201,response.json
    second_order=db.session.get(Order,response.json['order_id'])
    second_item=db.session.execute(db.select(OrderItem).where(OrderItem.order_id==second_order.id).order_by(OrderItem.id)).scalars().first()
    service.accept(item_id=second_item.id,actor_id=operator.id,committed_qty=30,eta=aware(second_cycle.arrival_at).isoformat(),session=db.session)
    db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield dict(base=f'http://127.0.0.1:{server.server_port}', draft=draft, order=order, item=item,
            manager=manager, operator=operator, second_order=second_order, second_item=second_item)
    finally:
        server.shutdown();thread.join(timeout=5)


@pytest.fixture
def browser(monkeypatch):
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runner:
        browser=runner.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge') or None,headless=True)
        errors=[]
        original=browser.new_context
        def new_context(*args, **kwargs):
            context=original(*args, **kwargs)
            context.on('page',lambda page:page.on('pageerror',lambda error:errors.append(str(error))))
            return context
        monkeypatch.setattr(browser,'new_context',new_context)
        yield browser
        browser.close()
        assert not errors,errors


def edit_draft(page, case):
    page.goto(f"{case['base']}/store/ordering?store_id={case['order'].store_id}&draft_id={case['draft']['id']}")
    page.wait_for_function('window.system2DraftEditor && !window.system2DraftEditor.busy()')
    row=page.locator(f".product-row[data-product-id='{case['item'].product_id}']")
    row.locator('.adjustment-details').evaluate('(e)=>e.open=true')
    return row


def database_barrier(page, case):
    # HTTP and assertions share the fixture's single transactional connection.
    # Drain the single-thread server before reading the DB from the test thread.
    assert page.request.get(case['base']+'/health').status==200


@pytest.mark.parametrize('action',['archive','rebuild'])
def test_two_windows_conflict_retains_unsaved_draft(review_server,browser,action):
    c=review_server;context=browser.new_context();page=context.new_page()
    login(page,c['base'],'manager1');row=edit_draft(page,c)
    row.locator('[data-field=final_qty]').fill('42');row.locator('[data-field=reason]').fill('第一視窗未儲存備註')
    other=context.new_page();other_row=edit_draft(other,c)
    other_row.locator('[data-field=final_qty]').fill('6');other_row.locator('[data-field=reason_code]').select_option('promotion')
    other_row.locator('[data-field=reason]').fill('另一視窗促銷調整')
    other.locator('#save-button').click()
    other.wait_for_function("document.querySelector('#draft-status').textContent.includes('已儲存')")
    page.locator(f'[data-draft-action={action}]').click()
    with page.expect_response(lambda r:r.url.endswith('/'+action) and r.request.method=='POST') as response:
        page.get_by_role('button',name='放棄未儲存修改並繼續',exact=True).click()
    assert response.value.status==409
    assert row.locator('[data-field=final_qty]').input_value()=='42'
    assert '輸入與暫存已保留' in page.locator('#draft-tools-status').inner_text()
    page.reload();page.wait_for_function('window.system2DraftEditor && !window.system2DraftEditor.busy()')
    assert page.locator(f".product-row[data-product-id='{c['item'].product_id}'] [data-field=final_qty]").input_value()=='42'
    assert '本機輸入已保留' in page.locator('#draft-status').inner_text()
    database_barrier(page,c);db.session.expire_all()
    saved=ordering_service.get_draft(c['manager'],c['draft']['id'])
    assert saved['status']=='DRAFT'
    assert next(i for i in saved['items'] if i['product_id']==c['item'].product_id)['final_qty']==6
    context.close()


@pytest.mark.parametrize('action',['archive','rebuild'])
@pytest.mark.parametrize('choice',['save','discard'])
def test_draft_explicit_save_or_discard_preserves_server_history(review_server,browser,action,choice):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'manager1');row=edit_draft(page,c)
    row.locator('[data-field=final_qty]').fill('42');row.locator('[data-field=reason_code]').select_option('promotion')
    row.locator('[data-field=reason]').fill('人工促銷備註保留')
    page.locator(f'[data-draft-action={action}]').click()
    with page.expect_response(lambda r:r.url.endswith('/'+action) and r.request.method=='POST') as result:
        page.get_by_role('button',name='儲存後繼續' if choice=='save' else '放棄未儲存修改並繼續',exact=True).click()
    assert result.value.status==(200 if action=='archive' else 201)
    if action=='archive':page.wait_for_url(f"{c['base']}/?store_id={c['order'].store_id}")
    else:page.wait_for_url(lambda url:'/store/ordering?' in url and f"draft_id={c['draft']['id']}" not in url)
    database_barrier(page,c);db.session.expire_all()
    saved=ordering_service.get_draft(c['manager'],c['draft']['id'])
    assert saved['status']=='ARCHIVED'
    line=next(i for i in saved['items'] if i['product_id']==c['item'].product_id)
    original=next(i for i in c['draft']['items'] if i['product_id']==c['item'].product_id)['final_qty']
    assert line['final_qty']==(42 if choice=='save' else original)
    if choice=='save':assert line['reason']=='人工促銷備註保留'
    if action=='rebuild':
        page.wait_for_function('window.system2DraftEditor && !window.system2DraftEditor.busy()')
        rebuilt_id=int(page.locator('#draft-tools').get_attribute('data-id'))
        rebuilt=ordering_service.get_draft(c['manager'],rebuilt_id)
        assert next(i for i in rebuilt['items'] if i['product_id']==c['item'].product_id)['final_qty']==(42 if choice=='save' else original)
    assert page.evaluate("Object.keys(sessionStorage).filter(k=>k.startsWith('system2-ordering:')).length")==0
    context.close()


def test_management_initial_failure_retry_and_saved_refresh_failure(review_server,browser):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'admin')
    calls=[]
    def broken_catalog(route):
        calls.append(route.request.url)
        route.fulfill(status=503,json={'error':{'message':'受控載入失敗'}})
    page.route('**/api/admin/catalog?*',broken_catalog)
    page.goto(c['base']+'/admin')
    page.get_by_role('button',name='重試載入設定',exact=True).wait_for()
    page.get_by_role('button',name='儲存設定',exact=True).click()
    assert '請重試載入設定' in page.locator('#admin-status').inner_text()
    page.unroute('**/api/admin/catalog?*',broken_catalog)
    page.get_by_role('button',name='重試載入設定',exact=True).click();page.locator('.admin-row').first.wait_for()
    page.locator('.admin-row').first.click()
    sku=page.locator('#admin-form [name=sku]').input_value()
    page.locator('#admin-form [name=name]').fill('已成功儲存但刷新失敗')
    page.route('**/api/admin/catalog?*',broken_catalog)
    with page.expect_response(lambda r:'/api/admin/products/' in r.url and r.request.method=='PATCH') as response:
        page.get_by_role('button',name='儲存設定',exact=True).click()
    assert response.value.status==200
    page.wait_for_function("document.querySelector('#admin-status').textContent.includes('資料已儲存，畫面刷新失敗')")
    database_barrier(page,c);db.session.expire_all()
    product=db.session.execute(db.select(Product).where(Product.sku==sku)).scalar_one()
    assert product.name=='已成功儲存但刷新失敗'
    db.session.commit()
    page.unroute('**/api/admin/catalog?*',broken_catalog)
    page.get_by_role('button',name='重試載入設定',exact=True).click()
    page.locator('.admin-row').filter(has_text='已成功儲存但刷新失敗').wait_for()
    assert page.get_by_role('button',name='儲存設定',exact=True).is_enabled()
    context.close()


def ship_form(page):
    return page.locator('form').filter(has=page.get_by_role('button',name='原訂出貨（非補送）',exact=True)).first


@pytest.mark.parametrize('failure',['401','403','network'])
def test_fulfillment_auth_and_network_recovery(review_server,browser,failure):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'operator')
    open_order(page,c['base'],'/headquarters/fulfillment',c['order'].id)
    form=ship_form(page)
    url=f"**/api/fulfillment/orders/{c['order'].id}/shipments"
    def fail(route):
        if failure=='network':route.abort('connectionreset')
        else:route.fulfill(status=int(failure),json={'error':{'code':'UNAUTHENTICATED' if failure=='401' else 'FORBIDDEN','message':'受控權限失敗'}})
    page.route(url,fail)
    form.get_by_role('button',name='原訂出貨（非補送）',exact=True).click()
    page.wait_for_function("Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:')) && !!document.querySelector('#fulfillment-error').textContent")
    stored=page.evaluate("Object.values(localStorage).filter(v=>v.includes('request_key'))")
    assert len(stored)==1
    if failure=='403':
        assert page.locator('#fulfillment-store').is_enabled()
        page.locator('#fulfillment-store').select_option(str(c['second_order'].store_id))
        page.wait_for_function('id=>document.querySelector("#fulfillment-detail").dataset.loadedOrderId===String(id)',arg=c['second_order'].id)
        assert ship_form(page).get_by_role('button',name='原訂出貨（非補送）',exact=True).is_enabled()
        with page.expect_response(lambda r:r.url.endswith(f"/{c['second_order'].id}/shipments") and r.request.method=='POST') as other:
            ship_form(page).get_by_role('button',name='原訂出貨（非補送）',exact=True).click()
        assert other.value.status==200
        page.wait_for_function("document.querySelector('#fulfillment-status').textContent.includes('操作已完成')")
        assert page.evaluate("Object.values(localStorage).filter(v=>v.includes('request_key')).length")==1
    else:
        assert page.locator('#fulfillment-store').is_disabled()
        assert page.get_by_role('button',name='以原內容重試',exact=True).is_enabled()
    page.unroute(url,fail)
    if failure=='401':
        # Cookies actually expire, then the original identity logs in and restores evidence.
        context.clear_cookies();login(page,c['base'],'operator')
        page.goto(f"{c['base']}/headquarters/fulfillment?store_id={c['order'].store_id}&order_id={c['order'].id}")
        page.wait_for_function('id=>document.querySelector("#fulfillment-detail").dataset.loadedOrderId===String(id)',arg=c['order'].id)
    retry=page.get_by_role('button',name='重新檢查權限並重試' if failure=='403' else '以原內容重試',exact=True)
    with page.expect_response(lambda r:r.url.endswith(f"/{c['order'].id}/shipments") and r.request.method=='POST') as retried:
        retry.click()
    assert retried.value.status==200
    page.wait_for_function("!Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:'))")
    page.wait_for_function('id=>document.querySelector("#fulfillment-detail").dataset.loadedOrderId===String(id)',arg=c['order'].id)
    database_barrier(page,c);db.session.expire_all()
    shipments=db.session.execute(db.select(Shipment).where(Shipment.order_id==c['order'].id)).scalars().all()
    assert len(shipments)==1
    context.close()


def test_pending_operation_does_not_transfer_to_new_account(review_server,browser):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'operator')
    open_order(page,c['base'],'/headquarters/fulfillment',c['order'].id)
    url=f"**/api/fulfillment/orders/{c['order'].id}/shipments"
    page.route(url,lambda route:route.abort('connectionreset'))
    ship_form(page).get_by_role('button',name='原訂出貨（非補送）',exact=True).click()
    page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
    other=context.new_page();login(other,c['base'],'admin')
    page.unroute(url)
    page.get_by_role('button',name='以原內容重試',exact=True).click()
    page.wait_for_function("document.querySelector('#fulfillment-error').textContent.includes('帳號已變更')")
    assert page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('system2-fulfillment:'))")
    assert page.locator('#fulfillment-store').is_disabled()
    database_barrier(page,c);db.session.expire_all()
    assert not db.session.execute(db.select(Shipment.id).where(Shipment.order_id==c['order'].id)).first()
    db.session.commit()
    other.goto(c['base']+'/headquarters/fulfillment')
    other.wait_for_function('document.querySelector("#fulfillment-detail").dataset.loadedOrderId')
    assert other.get_by_role('button',name='以原內容重試',exact=True).count()==0
    context.close()


def test_real_role_change_stops_retry_and_preserves_original_request(review_server,browser):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'operator')
    open_order(page,c['base'],'/headquarters/fulfillment',c['order'].id)
    url=f"**/api/fulfillment/orders/{c['order'].id}/shipments"
    page.route(url,lambda route:route.abort('connectionreset'))
    ship_form(page).get_by_role('button',name='原訂出貨（非補送）',exact=True).click()
    page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
    saved=page.evaluate("Object.values(localStorage).find(v=>v.includes('request_key'))")
    database_barrier(page,c)
    c['operator'].role='manager'
    c['operator'].stores=[db.session.get(Store,c['second_order'].store_id)]
    db.session.commit()
    page.unroute(url)
    page.get_by_role('button',name='以原內容重試',exact=True).click()
    page.get_by_role('button',name='重新檢查權限並重試',exact=True).wait_for()
    assert '角色權限已變更' in page.locator('#fulfillment-error').inner_text()
    import json
    current=page.evaluate("Object.values(localStorage).find(v=>v.includes('request_key'))")
    assert json.loads(current)['body']==json.loads(saved)['body']
    assert page.locator('#fulfillment-store').is_enabled()
    database_barrier(page,c);db.session.expire_all()
    assert not db.session.execute(db.select(Shipment.id).where(Shipment.order_id==c['order'].id)).first()
    context.close()


def test_real_store_permission_revocation_keeps_evidence_and_other_receipts_work(review_server,browser):
    c=review_server
    second_store=db.session.get(Store,c['second_order'].store_id)
    c['manager'].stores.append(second_store)
    for order,item in [(c['order'],c['item']),(c['second_order'],c['second_item'])]:
        service.ship(order_id=order.id,actor_id=c['operator'].id,request_key=f'prepare-{order.id}',
            lines=[dict(item_id=item.id,quantity=30,eta=aware(item.eta).isoformat())],session=db.session)
    db.session.commit()
    context=browser.new_context();page=context.new_page();login(page,c['base'],'manager1')
    open_order(page,c['base'],'/store/receiving',c['order'].id)
    form=page.locator('form').filter(has=page.get_by_role('button',name='標記到貨待查',exact=True)).first
    form.locator('[name=reason]').fill('到貨未明，保存原操作')
    page.route('**/api/fulfillment/shipment-items/*/unknown',lambda route:route.abort('connectionreset'))
    form.get_by_role('button',name='標記到貨待查',exact=True).click()
    page.get_by_role('button',name='以原內容重試',exact=True).wait_for()
    saved=page.evaluate("Object.values(localStorage).find(v=>v.includes('request_key'))")
    database_barrier(page,c)
    first_store=db.session.get(Store,c['order'].store_id)
    c['manager'].stores.remove(first_store)
    db.session.commit()
    page.unroute('**/api/fulfillment/shipment-items/*/unknown')
    page.get_by_role('button',name='以原內容重試',exact=True).click()
    page.get_by_role('button',name='重新檢查權限並重試',exact=True).wait_for()
    assert '原操作權限已變更' in page.locator('.fulfillment-app').inner_text()
    assert page.locator('#fulfillment-store').is_enabled()
    page.locator('#fulfillment-store').select_option(str(c['second_order'].store_id))
    page.wait_for_function('id=>document.querySelector("#fulfillment-detail").dataset.loadedOrderId===String(id)',arg=c['second_order'].id)
    receipt=page.locator('form').filter(has=page.get_by_role('button',name='確認本批收貨',exact=True)).first
    receipt.get_by_role('button',name='確認本批收貨',exact=True).click()
    page.wait_for_function("document.querySelector('#fulfillment-status').textContent.includes('操作已完成')")
    page.wait_for_function('id=>document.querySelector("#fulfillment-detail").dataset.loadedOrderId===String(id)',arg=c['second_order'].id)
    import json
    current=page.evaluate("Object.values(localStorage).find(v=>v.includes('request_key'))")
    assert json.loads(current)['body']==json.loads(saved)['body']
    database_barrier(page,c);db.session.expire_all()
    stock=db.session.execute(db.select(Inventory).where(Inventory.store_id==c['second_order'].store_id,
        Inventory.product_id==c['second_item'].product_id)).scalar_one()
    assert stock.book_physical_qty==50
    context.close()


@pytest.mark.parametrize('action',['archive','rebuild'])
def test_draft_api_failure_preserves_unsaved_fields_and_cache(review_server,browser,action):
    c=review_server;context=browser.new_context();page=context.new_page();login(page,c['base'],'manager1');row=edit_draft(page,c)
    row.locator('[data-field=final_qty]').fill('42');row.locator('[data-field=reason]').fill('失敗後仍需保留的備註')
    saved=page.evaluate('Object.values(sessionStorage)[0]')
    page.route(f'**/api/order-drafts/*/{action}',lambda route:route.fulfill(status=503,json={'error':{'message':'受控失敗'}}))
    page.locator(f'[data-draft-action={action}]').click()
    page.get_by_role('button',name='放棄未儲存修改並繼續',exact=True).click()
    page.wait_for_function("document.querySelector('#draft-tools-status').textContent.includes('輸入與暫存仍保留')")
    assert row.locator('[data-field=final_qty]').input_value()=='42'
    assert row.locator('[data-field=reason]').input_value()=='失敗後仍需保留的備註'
    assert page.evaluate('Object.values(sessionStorage)[0]')==saved
    database_barrier(page,c);db.session.expire_all()
    assert db.session.get(OrderDraft,c['draft']['id']).status=='DRAFT'
    context.close()
