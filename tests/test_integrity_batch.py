"""Batch optimization must match individual ledger validation."""
from dataclasses import asdict
from datetime import timedelta
import pytest
from app.extensions import db
from app.models import Inventory, InventoryReconciliation, User
from app.services.clock import business_now, round_window, utc_naive
from app.services.inventory import InventoryService


@pytest.mark.parametrize('scenario',['normal','negative','reconcile','older','future'])
def test_batch_matches_single_integrity(seeded,scenario):
    actor=db.session.execute(db.select(User).where(User.username=='manager1')).scalar_one()
    store_id=actor.stores[0].id
    row=db.session.execute(db.select(Inventory).where(Inventory.store_id==store_id)
        .order_by(Inventory.product_id)).scalars().first()
    baseline=round_window(business_now())[0]
    if scenario=='negative': row.book_physical_qty=-1;row.reconciliation_required=True
    if scenario=='reconcile':
        db.session.add(InventoryReconciliation(store_id=store_id,product_id=row.product_id,
            source_type='sales_covered',source_id='batch-check',reason='historical correction',
            created_at=utc_naive(baseline),status='OPEN'))
    if scenario=='older': row.counted_at-=timedelta(days=1)
    if scenario=='future': row.counted_at+=timedelta(days=1)
    db.session.flush()
    service=InventoryService()
    expected=service.get_integrity(store_id=store_id,product_id=row.product_id,baseline_at=baseline,session=db.session)
    result=service.get_integrities(store_id=store_id,product_ids=[row.product_id],baseline_at=baseline,session=db.session)
    assert asdict(result[row.product_id])==asdict(expected)
