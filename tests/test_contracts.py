from datetime import timedelta
from decimal import Decimal
from dataclasses import replace
import pytest
from app.extensions import db
from app.models import Store, Product, User, Order, Inventory, InventoryMovement
from app.contracts import OpenOrdersDTO, OpenSourceDTO, InventoryMutation, dto_dict, quantity
from app.testing.providers import ControlledOpenOrders, ControlledIntegrity, ControlledRuns, ControlledInventoryWriter
from app.testing.factories import make_order, make_run
from app.services.clock import business_now, round_window
from app.services.errors import DomainError
from app.providers import get_provider, register_provider


@pytest.mark.parametrize('module,expected', [('B', ('open_orders',)),
    ('C', ('runs','integrity','open_orders','fulfillment')), ('D', ('inventory_writer','orders'))])
def test_independent_module_boot(seeded, module, expected):
    from app import create_app
    from conftest import login
    isolated_connection = db.engine
    application = create_app({**seeded.config, 'MODULE_DEV': module, 'RATELIMIT_ENABLED': False})
    with application.app_context():
        engine = db.engines[None]
        db.engines[None] = isolated_connection
        for name in expected:
            assert get_provider(name) is not None
        client = application.test_client()
        assert login(client).status_code == 200
        response = client.get(f'/modules/{module.lower()}/')
        assert response.status_code == 200
        assert '非真實跨模組整合'.encode() in response.data
        assert client.get('/modules/x/').status_code == 404
        db.session.remove()
        db.engines[None] = engine
        engine.dispose()


def test_no_silent_fallback(seeded):
    seeded.config['MODULE_DEV'] = ''
    with pytest.raises(DomainError) as exc:
        get_provider('runs')
    assert exc.value.status == 503
    seeded.config['APP_ENV'] = 'production'
    with pytest.raises(ValueError):
        register_provider('runs', ControlledRuns(), test_only=True)
    with pytest.raises(ValueError):
        make_order(db.session)


@pytest.mark.parametrize('scenario,bucket', [('pending','U'), ('committed','C'),
    ('late','RISK'), ('disputed','RISK'), ('expired','RISK')])
def test_open_sources(seeded, scenario, bucket):
    store = db.session.execute(db.select(Store).order_by(Store.id)).scalars().first()
    now = business_now()
    b, _ = round_window(now)
    output = ControlledOpenOrders(scenario).get_open_orders(store_id=store.id, baseline_at=b,
        protection_end=b + timedelta(days=2), evaluated_at=now, session=db.session)
    source = output.sources[0]
    assert source.bucket == bucket and output.totals(source.product_id)[bucket] == 12
    with pytest.raises(ValueError):
        replace(output, sources=(source, source))


@pytest.mark.parametrize('scenario', ['gap', 'negative', 'no_count'])
def test_integrity_blocks(seeded, scenario):
    store = db.session.execute(db.select(Store)).scalars().first()
    product = db.session.execute(db.select(Product)).scalars().first()
    item = ControlledIntegrity(scenario).get_integrity(store_id=store.id, product_id=product.id,
        baseline_at=business_now(), session=db.session)
    assert item.h is None and not item.usable


@pytest.mark.parametrize('scenario', ['normal', 'direct', 'insufficient', 'manual', 'time_risk'])
def test_run_null_manual_and_time_risk(seeded, scenario):
    store = db.session.execute(db.select(Store)).scalars().first()
    actor = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    provider = ControlledRuns(scenario)
    run = provider.get_run(run_id=1, store_id=store.id, actor_id=actor.id, session=db.session)
    assert run.items[0].suggested_qty == (None if scenario in ('direct','insufficient') else 30)
    encoded = seeded.json.loads(seeded.json.dumps(dto_dict(run)))
    assert encoded['items'][0]['mu'] == (None if scenario in ('direct','insufficient') else '20')
    updated = provider.evaluate(run_id=1, store_id=store.id, actor_id=actor.id, cycle_id=run.cycle_id,
        final_quantities={run.items[0].product_id: 1002}, manual_confirmations=(),
        evaluated_at=run.baseline_at + timedelta(minutes=40), session=db.session)
    codes = {w.code for w in updated.items[0].warnings}
    assert 'LARGE_QUANTITY' in codes
    if scenario == 'time_risk':
        assert 'LOGISTICS_RISK' in codes
    if scenario in ('direct', 'insufficient'):
        assert updated.items[0].mu is None and updated.items[0].suggested_qty is None


def test_fixture_order_constraints_and_inventory_rollback(seeded):
    order, item = make_order(db.session)
    assert order.fixture_only and item.original_qty == 30
    row = db.session.execute(db.select(Inventory).where(Inventory.store_id == order.store_id,
        Inventory.product_id == item.product_id)).scalar_one()
    mutation = InventoryMutation(order.store_id, item.product_id, 'receipt', 'controlled-failure-1',
        10, 0, row.version, order.user_id, business_now(), '受控測試供應者收貨')
    savepoint = db.session.begin_nested()
    with pytest.raises(DomainError):
        ControlledInventoryWriter(fail_after_write=True).apply_movement(mutation=mutation, session=db.session)
    savepoint.rollback()
    db.session.expire_all()
    assert row.book_physical_qty == 20
    assert db.session.execute(db.select(InventoryMovement).where(InventoryMovement.source_id == mutation.source_id)).first() is None
    provider = ControlledInventoryWriter()
    result = provider.apply_movement(mutation=mutation, session=db.session)
    assert result.physical_book == 30
    assert provider.apply_movement(mutation=mutation, session=db.session).replayed
    with pytest.raises(DomainError) as exc:
        provider.apply_movement(mutation=replace(mutation, physical_delta=11), session=db.session)
    assert exc.value.code == 'IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('value', [True, False, -1, 1.2, '1000', None, 1000001, float('inf')])
def test_quantity_rejects_invalid(value):
    with pytest.raises(DomainError):
        quantity(value)


def test_quantity_four_digits():
    assert quantity(1000) == 1000


def test_c_factory_run_can_anchor_real_draft(seeded):
    from app.models import OrderDraft
    from app.services.clock import utc_naive
    run = make_run(db.session)
    dto = ControlledRuns().get_run(run_id=run.id, store_id=run.store_id,
        actor_id=run.actor_id, session=db.session)
    assert all(item.run_item_id is not None for item in dto.items)
    draft = OrderDraft(store_id=run.store_id, user_id=run.actor_id, run_id=run.id,
        cycle_id=run.cycle_id, created_at=utc_naive(business_now()), updated_at=utc_naive(business_now()))
    db.session.add(draft)
    db.session.flush()
    assert draft.id is not None
