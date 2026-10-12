"""Mixed-source regressions and B/C/D provider handover safeguards on MySQL."""
from datetime import timedelta
import pytest
from app.extensions import db
from app.models import Store, User, Order, OrderDraft, ReplenishmentRun, Inventory, InventoryMovement, BusinessClock
from app.providers import get_provider, register_provider
from app.services.clock import business_now, utc_naive
from app.services.errors import DomainError
from app.services.orders import ordering_service
from app.services.replenishment import ReplenishmentService
from app.services.run_sources import latest_run
from app.testing.factories import make_run, make_order
from app.testing.providers import ControlledRuns, ControlledInventoryWriter, install_test_providers
from app.contracts import InventoryMutation
from conftest import login
from test_replenishment import case, generate


def actor():
    return db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()


@pytest.mark.parametrize('module', ['', 'C'])
def test_real_provider_only_fixture_runs_shows_preparation(seeded, module):
    seeded.config['MODULE_DEV'] = module
    store = actor().stores[0]
    make_run(db.session, store_id=store.id)
    make_order(db.session, store_id=store.id)
    assert latest_run(store.id) is None
    client = seeded.test_client()
    assert login(client).status_code == 200
    assert client.get('/').status_code == 200
    response = client.get(f'/store/ordering?store_id={store.id}')
    assert response.status_code == 200
    assert '準備補貨建議'.encode() in response.data
    assert client.get('/api/stores/current/dashboard').json['latest_run_id'] is None
    if module:
        install_test_providers(module)
        response = client.get('/modules/c/')
        assert response.status_code == 200
        assert '真實服務'.encode() in response.data and '受控替身'.encode() in response.data
        assert '目前沒有相容'.encode() in response.data


def test_newer_fixture_cannot_hide_real_run(case, seeded):
    run = generate(case)
    db.session.get(BusinessClock, 1).business_anchor = utc_naive(business_now() + timedelta(minutes=1))
    db.session.flush()
    fake = make_run(db.session, store_id=run.store_id)
    assert fake.actual_generated_at > db.session.get(ReplenishmentRun, run.run_id).actual_generated_at
    assert latest_run(run.store_id).id == run.run_id
    other = db.session.execute(db.select(Store).where(Store.id != run.store_id)).scalars().first()
    assert latest_run(other.id) is None
    client = seeded.test_client()
    assert login(client).status_code == 200
    assert client.get(f'/store/ordering?store_id={run.store_id}').status_code == 200
    assert client.get('/api/stores/current/dashboard').json['latest_run_id'] == run.run_id
    with pytest.raises(DomainError) as error:
        get_provider('runs').get_run(run_id=fake.id, store_id=run.store_id, actor_id=actor().id, session=db.session)
    assert error.value.code == 'PROVIDER_MISMATCH'


def test_controlled_provider_chooses_its_own_source(case):
    real = generate(case)
    fake = make_run(db.session, store_id=real.store_id)
    register_provider('runs', ControlledRuns(), test_only=True)
    assert latest_run(real.store_id).id == fake.id


def test_stale_draft_is_preserved_and_cannot_be_previewed_or_changed(seeded):
    manager = actor()
    fake = make_run(db.session, store_id=manager.stores[0].id)
    register_provider('runs', ControlledRuns(), test_only=True)
    ordering_service.acknowledge_intro(manager, True)
    draft = ordering_service.create_draft(manager, store_id=fake.store_id, run_id=fake.id, cycle_id=fake.cycle_id)
    register_provider('runs', ReplenishmentService())
    before = ordering_service.get_draft(manager, draft['id'])
    assert not before['source_available']
    client = seeded.test_client()
    assert login(client).status_code == 200
    response = client.get(f"/store/ordering?store_id={fake.store_id}&draft_id={draft['id']}")
    assert response.status_code == 200
    assert '原草稿已保留'.encode() in response.data
    assert b'id="preview-button"' not in response.data
    for operation in (lambda: ordering_service.preview(manager, draft['id'], draft['version']),
            lambda: ordering_service.update_draft(manager, draft['id'], {'expected_version': draft['version'], 'items': draft['items']})):
        with pytest.raises(DomainError) as error:
            operation()
        assert error.value.code == 'DRAFT_SOURCE_UNAVAILABLE'
    assert ordering_service.get_draft(manager, draft['id']) == before
    assert db.session.get(OrderDraft, draft['id']).status == 'DRAFT'


def test_seed_c_does_not_add_controlled_runs_after_b_install(seeded):
    from app.testing.seed import seed_module_data
    before = db.session.execute(db.select(db.func.count(ReplenishmentRun.id))).scalar_one()
    seed_module_data('C')
    assert db.session.execute(db.select(db.func.count(ReplenishmentRun.id))).scalar_one() == before


@pytest.mark.parametrize('module', ['B', 'C', 'D'])
def test_module_injection_preserves_all_installed_real_providers(seeded, module):
    slots = dict(seeded.extensions['service_providers'])
    install_test_providers(module)
    for name, entry in slots.items():
        assert seeded.extensions['service_providers'][name] == entry


def test_real_fulfillment_never_receives_factory_or_other_store_order(seeded):
    class MustNotBeCalled:
        def get_summary(self, **kwargs):
            pytest.fail('No real order in this store: provider must not receive a fake ID')
    seeded.config['MODULE_DEV'] = 'C'
    install_test_providers('C')
    register_provider('fulfillment', MustNotBeCalled())
    make_order(db.session)
    client = seeded.test_client()
    assert login(client).status_code == 200
    response = client.get('/modules/c/')
    assert response.status_code == 200
    assert '本門市尚無可查詢'.encode() in response.data


def test_d_module_marks_factory_data_and_real_inventory(seeded):
    seeded.config['MODULE_DEV'] = 'D'
    install_test_providers('D')
    make_order(db.session)
    client = seeded.test_client()
    assert login(client).status_code == 200
    response = client.get('/modules/d/')
    assert response.status_code == 200
    assert '工廠訂單，非正式送單'.encode() in response.data
    assert '真實服務'.encode() in response.data


def test_factory_order_is_not_visible_in_formal_order_routes(seeded):
    order, _ = make_order(db.session)
    client = seeded.test_client()
    assert login(client).status_code == 200
    assert client.get(f'/api/orders/{order.id}').status_code == 404
    assert client.get(f'/store/orders/{order.id}').status_code == 404
    assert client.get('/api/orders').json['total'] == 0


def test_d_caller_rollback_and_retry_use_real_b_writer(seeded):
    # Prospective D caller transaction, not a claim that D receipt is implemented.
    order, item = make_order(db.session)
    db.session.get(BusinessClock, 1).business_anchor = utc_naive(business_now() + timedelta(minutes=1))
    db.session.flush()
    row = db.session.execute(db.select(Inventory).where(Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    mutation = InventoryMutation(order.store_id, item.product_id, 'receipt', 'D-handover-rollback',
        10, 0, row.version, order.user_id, business_now(), 'D接入防護：真實B同交易')
    writer = get_provider('inventory_writer')
    store = db.session.get(Store, order.store_id)
    before = (row.book_physical_qty, row.version, store.calculation_version, order.version)
    with pytest.raises(RuntimeError):
        with db.session.begin_nested():
            order.version += 1
            writer.apply_movement(mutation=mutation, session=db.session)
            raise RuntimeError('D caller failed after B flush')
    db.session.expire_all()
    assert (row.book_physical_qty, row.version, store.calculation_version, order.version) == before
    assert db.session.execute(db.select(InventoryMovement.id).where(
        InventoryMovement.source_id == mutation.source_id)).first() is None
    result = writer.apply_movement(mutation=mutation, session=db.session)
    assert result.physical_book == before[0] + 10
    assert writer.apply_movement(mutation=mutation, session=db.session).replayed
    assert row.book_physical_qty == before[0] + 10


def test_old_controlled_movement_is_not_replayed_as_real_b(seeded):
    order, item = make_order(db.session)
    row = db.session.execute(db.select(Inventory).where(Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    mutation = InventoryMutation(order.store_id, item.product_id, 'receipt', 'D-legacy-controlled',
        10, 0, row.version, order.user_id, business_now(), '替身來源不能冒充正式入帳')
    ControlledInventoryWriter().apply_movement(mutation=mutation, session=db.session)
    with pytest.raises(DomainError) as error:
        get_provider('inventory_writer').apply_movement(mutation=mutation, session=db.session)
    assert error.value.code == 'SOURCE_RESULT_UNAVAILABLE'
    assert row.book_physical_qty == 30


def test_additive_demo_uses_real_b_and_preserves_existing_rows(seeded, monkeypatch):
    from app.services.ordering_demo import prepare_ordering_demo
    seeded.config['APP_ENV'] = 'demo'
    seeded.config['MODULE_DEV'] = 'C'
    install_test_providers('C')
    # Still an isolated test transaction. Replace only the demo URL guard.
    monkeypatch.setattr('app.services.ordering_demo.validate_database', lambda *args: None)
    existing = {row.id: (row.calculation_version, row.name) for row in db.session.execute(db.select(Store)).scalars()}
    text = prepare_ordering_demo(db.session)
    store = db.session.execute(db.select(Store).where(Store.code == 'BCDEMO')).scalar_one()
    run = latest_run(store.id)
    assert run.model_version == 'sma7-periodic-v1'
    assert '正式 D 未結來源' in text
    assert {row.id: (row.calculation_version, row.name) for row in db.session.execute(
        db.select(Store).where(Store.id.in_(existing))).scalars()} == existing
    dto = get_provider('runs').get_run(run_id=run.id, store_id=store.id,
        actor_id=run.actor_id, session=db.session)
    assert all(item.h == 20 and item.mu == 20 and item.suggested_qty == 30 for item in dto.items)
    before = [(table.name, db.session.execute(db.select(db.func.count()).select_from(table)).scalar_one())
        for table in db.metadata.tables.values()]
    assert '已存在' in prepare_ordering_demo(db.session)
    assert before == [(table.name, db.session.execute(db.select(db.func.count()).select_from(table)).scalar_one())
        for table in db.metadata.tables.values()]


def test_demo_preparation_rejects_test_environment(seeded):
    from app.services.ordering_demo import prepare_ordering_demo
    with pytest.raises(ValueError):
        prepare_ordering_demo(db.session)


@pytest.mark.parametrize('already_submitted', [False, True])
def test_provider_handover_blocks_new_submission_but_replays_success(seeded, client, already_submitted):
    from test_submission import _prepare, _preview, _submit_body, _write
    _, draft = _prepare(seeded, client)
    preview = _preview(client, draft)
    body = _submit_body(draft, preview)
    path = f"/api/order-drafts/{draft['id']}/submit"
    headers = {'Idempotency-Key': 'handover-original-request'}
    original = _write(client, 'POST', path, body, headers) if already_submitted else None
    if original:
        assert original.status_code == 201
    register_provider('runs', ReplenishmentService())
    response = _write(client, 'POST', path, body, headers)
    if already_submitted:
        assert response.status_code == 200
        assert response.json['replayed'] and response.json['order_id'] == original.json['order_id']
    else:
        assert response.status_code == 409
        assert response.json['error']['code'] == 'DRAFT_SOURCE_UNAVAILABLE'
        assert db.session.get(OrderDraft, draft['id']).status == 'DRAFT'
        assert db.session.execute(db.select(db.func.count(Order.id))).scalar_one() == 0
