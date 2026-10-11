"""Review regressions: reachable preparation, compatible history and bounded reads."""
from sqlalchemy import event

from app.extensions import db
from app.models import ReplenishmentRun
from app.services.manual_forecasting import ManualForecastService
from app.testing.factories import make_run
from conftest import login
from test_replenishment import case, generate


def test_home_links_to_data_and_preparation_without_fake_runs(seeded, client):
    make_run(db.session)
    assert login(client).status_code == 200
    response = client.get('/')
    assert response.status_code == 200
    assert '準備補貨建議'.encode() in response.data
    assert '資料管理'.encode() in response.data
    assert '正式庫存串接將'.encode() not in response.data


def test_saved_run_list_contains_only_readable_b_snapshots(case, client):
    real = generate(case)
    fake = make_run(db.session, store_id=real.store_id)
    assert login(client).status_code == 200
    context = client.get(f'/api/replenishment/context?store_id={real.store_id}')
    assert context.status_code == 200
    ids = [row['id'] for row in context.json['runs']]
    assert real.run_id in ids and fake.id not in ids
    for run_id in ids:
        assert client.get(f'/api/replenishment/runs/{run_id}?store_id={real.store_id}').status_code == 200


def _count_input_reads(operation):
    statements = []
    engine = db.engine
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = operation()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    counts = {table: sum(statement.lstrip().startswith('select') and f'from {table}' in statement
        for statement in statements) for table in ('sales_daily', 'manual_forecast_overrides')}
    print('input SELECT counts:', counts)
    assert all(count <= 1 for count in counts.values()), counts
    return result


def test_generation_batches_sales_and_latest_manual_values(case):
    manual = ManualForecastService()
    for value in ('5.125', '8.5'):
        latest = manual.save(store_id=case['store'].id, product_id=case['stocks'][0].product_id,
            actor_id=case['actor'].id, daily_demand=value, reason='本地活動需求，核對最新人工值',
            expected_version=case['store'].calculation_version, session=db.session)
    run = _count_input_reads(lambda: generate(case))
    assert len(run.items) == 10
    assert run.items[0].input_snapshot['manual_forecast'] == latest['manual_forecast']
    assert run.items[1].input_snapshot['manual_forecast'] is None
    assert len(run.items[0].input_snapshot['sales']) == 7
    assert run.items[0].suggested_qty == 42
    assert db.session.get(ReplenishmentRun, run.run_id).store_version == case['store'].calculation_version


def test_context_batches_sales_and_keeps_seven_day_window(case):
    products = _count_input_reads(lambda: ManualForecastService().options(store_id=case['store'].id,
        actor_id=case['actor'].id, session=db.session))
    assert len(products) == 10
    assert all(product['forecast_valid'] and len(product['sales']) == 7 for product in products)
