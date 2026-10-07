from datetime import timedelta
from uuid import uuid4
from flask import current_app
from app.extensions import db
from app.models import (Store, Product, User, DeliveryCycle, ReplenishmentRun, RunItem,
    OrderDraft, DraftItem, Order, OrderItem, OrderConfirmation)
from app.services.clock import business_now, utc_naive, aware


def require_fixture_mode():
    if current_app.config['APP_ENV'] != 'test' and not current_app.config['MODULE_DEV']:
        raise ValueError('測試工廠僅限 test 或明確模組開發模式')


def make_run(session, *, store_id=None, scenario='normal'):
    require_fixture_mode()
    from app.testing.providers import ControlledRuns
    from app.contracts import dto_dict
    store = session.get(Store, store_id) if store_id else session.execute(db.select(Store).order_by(Store.id)).scalars().first()
    username = 'manager1' if store.code == 'DEMO1' else 'manager2'
    actor = session.execute(db.select(User).where(User.username == username)).scalar_one()
    dto = ControlledRuns(scenario).get_run(run_id=0, store_id=store.id, actor_id=actor.id, session=session)
    to_json = lambda value: current_app.json.loads(current_app.json.dumps(value))
    row = ReplenishmentRun(store_id=store.id, cycle_id=dto.cycle_id, actor_id=actor.id,
        store_version=store.calculation_version, baseline_at=utc_naive(dto.baseline_at),
        actual_generated_at=utc_naive(dto.actual_generated_at), data_through_at=utc_naive(dto.data_through_at),
        risk_evaluated_at=utc_naive(dto.risk_evaluated_at), model_version=dto.model_version,
        warning_version=dto.warning_version, calculation_mode='model', snapshot=to_json(dto_dict(dto)))
    session.add(row)
    session.flush()
    for item in dto.items:
        session.add(RunItem(run_id=row.id, product_id=item.product_id, mode=item.mode,
            mu=item.mu, target_stock=item.target_stock, raw_qty=item.raw_qty,
            suggested_qty=item.suggested_qty, input_snapshot=to_json(item.input_snapshot),
            output_snapshot=to_json(dto_dict(item)), warnings=to_json([dto_dict(w) for w in item.warnings])))
    session.flush()
    return row


def make_order(session, *, store_id=None, product_id=None, quantity=30):
    """Persist real shared ORM rows but explicitly mark fixture_only, never simulate C submission."""
    require_fixture_mode()
    from app.contracts import quantity as valid_quantity
    valid_quantity(quantity, 1)
    store = session.get(Store, store_id) if store_id else session.execute(db.select(Store).order_by(Store.id)).scalars().first()
    product = session.get(Product, product_id) if product_id else session.execute(db.select(Product).order_by(Product.id)).scalars().first()
    user = session.execute(db.select(User).where(User.username == 'manager1' if store.code == 'DEMO1'
        else User.username == 'manager2')).scalar_one()
    cycle = session.execute(db.select(DeliveryCycle).where(DeliveryCycle.store_id == store.id)
        .order_by(DeliveryCycle.id)).scalars().first()
    now = utc_naive(business_now())
    snapshot = {'fixture_only': True, 'source': 'A03 formal-order test factory', 'original_qty': quantity}
    run = ReplenishmentRun(store_id=store.id, cycle_id=cycle.id, actor_id=user.id,
        store_version=store.calculation_version, baseline_at=cycle.baseline_at,
        actual_generated_at=now, data_through_at=cycle.baseline_at, risk_evaluated_at=now,
        model_version='fixture-v1', warning_version='1', calculation_mode='model', snapshot=snapshot)
    session.add(run)
    session.flush()
    item = RunItem(run_id=run.id, product_id=product.id, mode='model', mu=20,
        target_stock=50, raw_qty=30, suggested_qty=30, input_snapshot=snapshot,
        output_snapshot=snapshot, warnings=[])
    session.add(item)
    session.flush()
    draft = OrderDraft(store_id=store.id, user_id=user.id, cycle_id=cycle.id,
        run_id=run.id, status='SUBMITTED', created_at=now, updated_at=now)
    session.add(draft)
    session.flush()
    session.add(DraftItem(draft_id=draft.id, product_id=product.id, run_item_id=item.id, final_qty=quantity))
    order = Order(store_id=store.id, user_id=user.id, cycle_id=cycle.id, draft_id=draft.id,
        number='FIXTURE-' + uuid4().hex, submitted_at=now, fixture_only=True)
    session.add(order)
    session.flush()
    order_item = OrderItem(order_id=order.id, product_id=product.id, original_qty=quantity,
        product_snapshot={'sku': product.sku, 'name': product.name, 'pack_size': product.pack_size},
        deduction_expires_at=now + timedelta(minutes=60))
    session.add(order_item)
    session.add(OrderConfirmation(order_id=order.id, draft_id=draft.id, user_id=user.id, store_id=store.id,
        draft_version=1, store_version=store.calculation_version, token_hash=uuid4().hex + uuid4().hex,
        payload_hash=uuid4().hex + uuid4().hex, text_version='fixture-v1', warning_version='1',
        created_at=now, expires_at=now + timedelta(minutes=5), risk_evaluated_at=now,
        acknowledged_at=now, order_acknowledged=True, exception_acknowledgements=[], snapshot=snapshot))
    session.flush()
    return order, order_item
