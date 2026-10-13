"""B04 real Edge workflows; B services and isolated MySQL, controlled D only."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server
from app.extensions import db
from app.models import SalesDaily, Inventory
from test_replenishment import case
from browser_replenishment import open_runs

@pytest.fixture
def mode_server(case,seeded):
    stock=case['stocks'][2]; stock.physical_qty=stock.book_physical_qty=8
    row=db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id==case['store'].id,
        SalesDaily.product_id==stock.product_id,SalesDaily.business_date==case['b'].date())).scalar_one()
    db.session.delete(row);db.session.commit()
    server=make_server('127.0.0.1',0,seeded,threaded=False)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}',case
    finally:server.shutdown();thread.join(timeout=5)

def wait_message(page,text):
    page.wait_for_function("(text)=>document.querySelector('#run-message').textContent.includes(text)",arg=text)
    page.wait_for_function("!document.querySelector('#generate-run').disabled")

def set_direct(card,date):
    card.locator('[data-field=mode]').select_option('direct')
    for field,value in [('need-date',date),('need-qty','1000'),('special-reason','社區活動需要雨衣，已核對一千件數量'),
        ('arrangement','到貨後直接交付活動單位'),('direct-qty','1000')]:
        card.locator('[data-field='+field+']').fill(value)

@pytest.mark.parametrize('width',[1280,390,320])
def test_manual_history_direct_and_fresh_confirmation(mode_server,width):
    base,c=mode_server;pid=c['stocks'][2].product_id
    from playwright.sync_api import sync_playwright
    artifacts=Path('instance/browser-check');artifacts.mkdir(parents=True,exist_ok=True)
    before=[(s.product_id,s.book_physical_qty,s.version) for s in c['stocks']]
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
        open_runs(page,base)
        page.locator('.forecast-choices > summary').click()
        normal=page.locator('[data-forecast-product]').first
        normal.locator('summary').click()
        normal.locator('[data-field=historical-note]').fill('歷史社區活動照常納入七日平均')
        normal.locator('[data-action=save-event]').click()
        wait_message(page,'歷史註記已保存')
        manual=page.locator('[data-forecast-product="'+str(pid)+'"]')
        manual.locator('[data-field=mode]').select_option('manual')
        manual.locator('[data-field=daily-demand]').fill('5.1251')
        manual.locator('[data-field=manual-reason]').fill('本地活动需求已逐日核對，設定每日5.125件')
        manual.locator('[data-action=save-manual]').click()
        wait_message(page,'最多三位小數')
        manual.locator('[data-field=daily-demand]').fill('5.125')
        manual.locator('[data-action=save-manual]').click()
        wait_message(page,'人工預測已保存')
        assert '設定者id' in manual.inner_text() and '有效至' in manual.inner_text()
        assert not manual.locator('[data-field=confirmed]').is_checked()
        page.locator('#generate-run').click()
        wait_message(page,'請主動確認')
        manual.locator('[data-field=confirmed]').check()
        page.locator('#generate-run').click()
        wait_message(page,'補貨建議已保存')
        item=page.locator('[data-sku=SKU03]')
        assert '5.125' in item.inner_text() and '13件' in item.inner_text()
        assert page.locator('[data-sku=SKU01] [data-warning-code=HISTORICAL_EVENT]').is_visible()
        assert page.locator('[data-sku=SKU01] [data-warning-code=SPECIAL_DEMAND]').count()==0
        ack=item.locator('[data-manual-confirm-id]')
        assert not ack.is_checked()
        page.locator('#evaluate-run').click()
        wait_message(page,'試算完成')
        assert item.locator('[data-warning-code=FORECAST_INSUFFICIENT]').is_visible()
        ack.check();page.locator('#evaluate-run').click()
        wait_message(page,'試算完成')
        assert item.locator('[data-warning-code=FORECAST_INSUFFICIENT]').count()==0
        ack.check();item.locator('input[type=number]').fill('14')
        assert not ack.is_checked()
        item.locator('input[type=number]').fill('13')
        page.locator('#load-run').click();wait_message(page,'已讀取當時建議')
        assert not ack.is_checked()
        page.screenshot(path=str(artifacts/f'b04-manual-{width}.png'),full_page=True)
        set_direct(manual,'2026-10-09')
        page.locator('#generate-run').click();wait_message(page,'補貨建議已保存')
        assert manual.locator('[data-field=need-qty]').input_value()=='1000'
        assert manual.locator('[data-field=arrangement]').input_value()=='到貨後直接交付活動單位'
        page.locator('#refresh-run-context').click();wait_message(page,'門市版本已重新核對')
        assert manual.locator('[data-field=direct-qty]').input_value()=='1000'
        assert '無法計算' in item.inner_text() and '1008件' in item.inner_text()
        assert '無法評估需求缺口' in item.inner_text()
        assert item.locator('[data-warning-code=DIRECT_ORDER]').is_visible() and item.locator('[data-warning-code=CAPACITY]').is_visible()
        assert item.locator('svg').count()==0
        item.locator('input[type=number]').fill('1200')
        page.locator('#evaluate-run').click();wait_message(page,'試算完成')
        assert '1208件' in item.inner_text() and item.locator('input[type=number]').input_value()=='1200'
        page.locator('#load-run').click();wait_message(page,'已讀取當時建議')
        assert item.locator('input[type=number]').input_value()=='1000' and '1008件' in item.inner_text()
        page.evaluate("document.documentElement.style.fontSize='20px'")
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(artifacts/f'b04-direct-{width}.png'),full_page=True)
        assert not errors
        browser.close()
    db.session.expire_all()
    after=[(s.product_id,s.book_physical_qty,s.version) for s in db.session.execute(db.select(Inventory)
        .where(Inventory.store_id==c['store'].id).order_by(Inventory.product_id)).scalars()]
    assert after==before
