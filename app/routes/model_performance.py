"""Snapshot predictions versus subsequent confirmed daily sales, no hindsight."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, g, render_template
from app.extensions import db
from app.models import ReplenishmentRun, RunItem, SalesDaily, Product, DraftItem, OrderDraft
from app.services.access import require_role, authorize_store
from app.services.clock import aware, TAIPEI, business_now
from app.services.inputs import query_integer

bp = Blueprint('model_performance', __name__)


@bp.get('/store/model-performance')
@require_role('manager', 'admin')
def page():
    store_id = query_integer('store_id', '門市')
    if store_id is None and g.user.role == 'manager':
        store_id = next((s.id for s in g.user.stores if s.active), None)
    store = authorize_store(g.user, store_id, roles=('manager', 'admin'))
    page_number = query_integer('page', '頁碼', default=1, maximum=1_000_000)
    # Last snapshot per day/product avoids counting repeat calculations as new forecasts.
    from app.services.forecasting import MODEL_VERSION
    # Use the deployed model version, not a separately maintained label.
    selected = db.select(RunItem.product_id.label('product_id'), ReplenishmentRun.baseline_at.label('baseline'),
        db.func.max(RunItem.id).label('item_id')).join(ReplenishmentRun).where(
        ReplenishmentRun.store_id == store.id, ReplenishmentRun.model_version == MODEL_VERSION)\
        .group_by(RunItem.product_id, ReplenishmentRun.baseline_at).subquery()
    snapshots = db.session.execute(db.select(RunItem, ReplenishmentRun, Product).join(ReplenishmentRun)
        .join(Product, Product.id == RunItem.product_id).join(selected, selected.c.item_id == RunItem.id)
        .order_by(ReplenishmentRun.baseline_at.desc(), RunItem.id).offset((page_number-1)*50).limit(51)).all()
    dates = {aware(r.baseline_at).astimezone(TAIPEI).date()+timedelta(days=1) for _, r, _ in snapshots[:50]}
    actuals = {(s.product_id, s.business_date): s for s in db.session.execute(db.select(SalesDaily).where(
        SalesDaily.store_id == store.id, SalesDaily.business_date.in_(dates))).scalars()} if dates else {}
    run_ids = [r.id for _, r, _ in snapshots[:50]]
    adjustments = {}
    if run_ids:
        for item, draft in db.session.execute(db.select(DraftItem, OrderDraft).join(OrderDraft).where(
                OrderDraft.run_id.in_(run_ids), DraftItem.reason_code.is_not(None)).order_by(DraftItem.id)):
            adjustments.setdefault((draft.run_id, item.product_id), []).append(
                {'qty': item.final_qty, 'reason': item.reason or item.reason_code, 'draft': draft.id, 'status': draft.status})
    rows, errors = [], []
    for item, run, product in snapshots[:50]:
        target = aware(run.baseline_at).astimezone(TAIPEI).date()+timedelta(days=1)
        actual = actuals.get((item.product_id, target))
        complete = actual and aware(actual.interval_end) <= business_now()
        error = abs(item.mu - Decimal(actual.sold_qty)) if complete and actual.is_open and not actual.was_stockout and item.mu is not None else None
        if error is not None:
            errors.append(error)
        rows.append(dict(product=product.name, date=target, forecast=item.mu, mode=item.mode,
            actual=actual.sold_qty if complete else None, error=error,
            quality='缺貨／非正常營業，不納入 MAE' if complete and (actual.was_stockout or not actual.is_open) else '已完成區間' if complete else '尚無完整實際資料',
            adjustments=adjustments.get((run.id, item.product_id), [])))
    return render_template('store/model_performance.html', store=store, rows=rows, page=page_number,
        has_next=len(snapshots)>50, mae=sum(errors)/len(errors) if errors else None, samples=len(errors))
