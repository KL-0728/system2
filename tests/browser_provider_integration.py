"""Explicit Edge verification of empty, stale and real B-backed C pages."""
from pathlib import Path
from threading import Thread
import pytest
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
from app.extensions import db
from app.models import User
from app.providers import register_provider
from app.services.orders import ordering_service
from app.services.replenishment import ReplenishmentService
from app.testing.factories import make_run
from app.testing.providers import ControlledRuns
from test_replenishment import case, generate


@pytest.mark.parametrize('width', [1280, 390, 320])
@pytest.mark.parametrize('scenario', ['empty', 'stale', 'real', 'cached'])
def test_c_source_recovery_in_edge(case, seeded, width, scenario):
    manager = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    draft = None
    if scenario in ('real', 'cached'):
        generate(case)
    fake = make_run(db.session, store_id=case['store'].id)
    if scenario in ('stale', 'cached'):
        register_provider('runs', ControlledRuns(), test_only=True)
        ordering_service.acknowledge_intro(manager, True)
        draft = ordering_service.create_draft(manager, store_id=fake.store_id,
            run_id=fake.id, cycle_id=fake.cycle_id)
        register_provider('runs', ReplenishmentService())
    db.session.commit()  # Fixture outer transaction still rolls back at teardown.
    # Resolve expired ORM values before starting the server: its isolated fixture
    # shares one DB connection, which must never be used by two threads at once.
    query = f'?store_id={case["store"].id}' + (f'&draft_id={draft["id"]}' if scenario == 'stale' else '')
    server = make_server('127.0.0.1', 0, seeded, threaded=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    artifacts = Path('instance/browser-check')
    artifacts.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as runner:
            browser = runner.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/login')
            page.locator('#username').fill('manager1')
            page.locator('#password').fill('Synthetic-test-password-2026')
            page.get_by_role('button', name='登入', exact=True).click()
            response = page.goto(base + '/store/ordering' + query)
            assert response.status == 200
            page.evaluate("document.documentElement.style.fontSize = '20px'")
            if scenario in ('real', 'cached'):
                if scenario == 'real':
                    page.locator('#intro-ack').check()
                    page.get_by_role('button', name='確認並進入補貨').click()
                else:
                    page.evaluate('''draftId => {
                        const boot = JSON.parse(document.querySelector('#ordering-bootstrap').textContent);
                        sessionStorage.setItem(`system2-ordering:${boot.actor_id}:${boot.store_id}`,
                            JSON.stringify({runId: boot.run.run_id, draftId, draftVersion: 1,
                                items: [{product_id: boot.run.items[0].product_id, fields: {final_qty: '999'}}]}));
                    }''', draft['id'])
                    page.reload()
                    page.wait_for_function("document.querySelector('#global-error').textContent.includes('原草稿已保留')")
                page.locator('#preview-button').wait_for()
                assert page.locator('.product-row').count() == 10
                assert page.locator('.product-row').first.locator('[data-field="final_qty"]').input_value() == '42'
            else:
                assert page.get_by_role('link', name='準備補貨建議', exact=True).is_visible()
                assert page.locator('#preview-button').count() == 0
                if draft:
                    assert '原草稿已保留' in page.get_by_role('alert').inner_text()
                    page.get_by_role('link', name='使用本輪建議建立新草稿', exact=True).click()
                    assert 'draft_id=' not in page.url
            assert not errors, errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / f'provider-{scenario}-{width}.png'), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
