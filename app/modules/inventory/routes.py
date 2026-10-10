"""B02 manager-only data maintenance; canonical APIs remain compatible with spec."""
from dataclasses import asdict
from datetime import datetime, timezone
import csv
from io import StringIO

from flask import Blueprint, g, jsonify, render_template, request, Response
from app.contracts import dto_dict, quantity
from app.extensions import db
from app.models import (Inventory, InventoryCount, InventoryCountRevision, InventoryReconciliation,
    Product, SalesDaily, SalesImportBatch)
from app.services.access import authorize_store, require_role
from app.services.clock import aware, business_now, round_window, TAIPEI
from app.services.errors import DomainError
from app.services.inventory import InventoryService
from app.services.sales import SalesService, COLUMNS
from app.services.version import transaction

bp = Blueprint('inventory', __name__)
sales_service = SalesService()
inventory_service = InventoryService()


def _payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise DomainError('INVALID_INPUT', '請提供 JSON 物件', 400)
    return value


def _store(store_id=None):
    if store_id is None:
        store = next((row for row in g.user.stores if row.active), None)
        if store is None:
            raise DomainError('NOT_FOUND', '沒有可操作的門市', 404)
        store_id = store.id
    quantity(store_id, minimum=1, maximum=2_147_483_647)
    return authorize_store(g.user, store_id, roles=('manager',))


def _query_store():
    raw = request.args.get('store_id')
    if raw is None:
        return _store()
    if not raw.isascii() or not raw.isdecimal():
        raise DomainError('INVALID_INPUT', '門市識別須為整數', 400)
    return _store(int(raw))


def _time(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise DomainError('INVALID_TIME', '時間須含時區，例如2026-10-09T21:00:00+08:00', 400)


@bp.get('/store/data')
@require_role('manager')
def data_page():
    store = _query_store()
    return render_template('inventory/data.html', store=store, actor_id=g.user.id)


@bp.get('/api/inventory/status')
@require_role('manager')
def status():
    store = _query_store()
    with transaction():
        b, cutoff = round_window(business_now())
        products = db.session.execute(db.select(Product).join(Inventory, Inventory.product_id == Product.id)
            .where(Inventory.store_id == store.id).order_by(Product.id)).scalars().all()
        items = []
        for product in products:
            integrity = inventory_service.get_integrity(store_id=store.id, product_id=product.id,
                baseline_at=b, session=db.session)
            inventory = db.session.execute(db.select(Inventory).where(Inventory.store_id == store.id,
                Inventory.product_id == product.id)).scalar_one()
            count = db.session.execute(db.select(InventoryCount).where(InventoryCount.store_id == store.id,
                InventoryCount.product_id == product.id, InventoryCount.cutoff_at == b.replace(tzinfo=None))).scalar_one_or_none()
            revision = db.session.execute(db.select(InventoryCountRevision).where(
                InventoryCountRevision.count_id == count.id, InventoryCountRevision.revision == count.version)
                ).scalar_one() if count else None
            sales = db.session.execute(db.select(SalesDaily).where(SalesDaily.store_id == store.id,
                SalesDaily.product_id == product.id, SalesDaily.business_date == b.astimezone(TAIPEI).date())
                ).scalar_one_or_none()
            tasks = db.session.execute(db.select(InventoryReconciliation).where(
                InventoryReconciliation.store_id == store.id, InventoryReconciliation.product_id == product.id,
                InventoryReconciliation.status == 'OPEN')).scalars().all()
            items.append(dict(sku=product.sku, name=product.name, pack_size=product.pack_size,
                **dto_dict(integrity), usable=integrity.usable, h=integrity.h,
                last_physical_qty=inventory.physical_qty, last_unsellable_qty=inventory.unsellable_qty,
                last_counted_at=aware(inventory.counted_at).isoformat(),
                count_version=count.version if count else None,
                count_physical_qty=revision.physical_qty if revision else None,
                count_unsellable_qty=revision.unsellable_qty if revision else None,
                sales=None if sales is None else dict(sales_id=sales.id, sold_qty=sales.sold_qty,
                    batch_id=sales.batch_id, import_mode=sales.import_mode,
                    applied_at=aware(sales.applied_at).isoformat() if sales.applied_at else None),
                reconciliations=[dict(id=task.id, reason=task.reason, source_type=task.source_type) for task in tasks]))
        batches = db.session.execute(db.select(SalesImportBatch).where(SalesImportBatch.store_id == store.id)
            .order_by(SalesImportBatch.id.desc()).limit(30)).scalars().all()
        result = dict(store_id=store.id, code=store.code, store_version=store.calculation_version,
            baseline_at=b.isoformat(), deadline_at=cutoff.isoformat(), items=items,
            batches=[dict(id=batch.id, source_batch_id=batch.source_batch_id, import_mode=batch.import_mode,
                replaces_batch_id=batch.replaces_batch_id, created_at=aware(batch.created_at).isoformat()) for batch in batches])
    return jsonify(result)


@bp.post('/api/sales/import/validate')
@require_role('manager')
def validate_sales():
    data = _payload()
    _store(data.get('store_id'))
    with transaction():
        result = sales_service.validate(payload=data, actor_id=g.user.id, session=db.session)
    return jsonify(result)


@bp.post('/api/sales/import/commit')
@require_role('manager')
def commit_sales():
    data = _payload()
    _store(data.get('store_id'))
    with transaction():
        result = sales_service.commit(payload=data, actor_id=g.user.id,
            validation_token=data.get('validation_token'), session=db.session)
    return jsonify(result), 200 if result['replayed'] else 201


@bp.post('/api/inventory/counts')
@require_role('manager')
def submit_count():
    data = _payload()
    store = _store(data.get('store_id'))
    product_id = quantity(data.get('product_id'), minimum=1, maximum=2_147_483_647)
    with transaction():
        result = inventory_service.submit_count(store_id=store.id, product_id=product_id, actor_id=g.user.id,
            cutoff_at=_time(data.get('cutoff_at')), physical_qty=data.get('physical_qty'),
            unsellable_qty=data.get('unsellable_qty'), expected_version=data.get('expected_version'),
            request_key=data.get('request_key'), reason=data.get('reason'), correction=data.get('correction', False),
            expected_count_version=data.get('expected_count_version'), session=db.session)
    return jsonify(asdict(result)), 200 if result.replayed else 201


@bp.get('/store/data/sample.csv')
@require_role('manager')
def sample_csv():
    store = _query_store()
    b, _ = round_window(business_now())
    day = b.astimezone(TAIPEI).date().isoformat()
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    products = db.session.execute(db.select(Product).join(Inventory, Inventory.product_id == Product.id)
        .where(Inventory.store_id == store.id).order_by(Product.id)).scalars()
    for product in products:
        sold = 2 if product.sku == 'SKU01' else (25 if product.sku == 'SKU02' else 0)
        writer.writerow([f'B02-{day}', store.code, product.sku, day, sold, 0, 1])
    return Response('\ufeff' + stream.getvalue(), content_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="sales_sample.csv"'})


# Only B's blueprint contributes this local, additive preparation command.
from app.modules.inventory.demo import register_demo
register_demo(bp)
