"""B05 manager-only operations, atomic writes and read-only history."""
from dataclasses import asdict
from datetime import datetime
from flask import g, jsonify, request
from app.contracts import quantity
from app.extensions import db
from app.models import InventoryMovement, InventoryReconciliation, Product
from app.services.access import require_role
from app.services.clock import aware
from app.services.inventory import _business_now
from app.services.inventory_operations import InventoryOperations
from app.services.version import transaction

def register_operations(bp, store, query_store, payload, time_value):
    service=InventoryOperations()
    def removal(kind):
        data=payload(); target=store(data.get('store_id'))
        with transaction():
            result=service.remove_damaged(store_id=target.id,product_id=data.get('product_id'),
                actor_id=g.user.id,kind=kind,qty=data.get('qty'),expected_version=data.get('expected_version'),
                source_id=data.get('source_id'),occurred_at=time_value(data.get('occurred_at')),
                reason=data.get('reason'),session=db.session)
        return jsonify(asdict(result)),200 if result.replayed else 201

    @bp.post('/api/inventory/disposals')
    @require_role('manager')
    def dispose(): return removal('disposal')

    @bp.post('/api/inventory/returns')
    @require_role('manager')
    def return_damaged(): return removal('return')

    @bp.post('/api/inventory/reconciliations/<int:task_id>/resolve')
    @require_role('manager')
    def resolve(task_id):
        data=payload(); target=store(data.get('store_id'))
        with transaction():
            result=service.resolve_with_count(task_id=task_id,expected_task_version=data.get('expected_task_version'),
                store_id=target.id,product_id=quantity(data.get('product_id'),minimum=1,maximum=2_147_483_647),
                actor_id=g.user.id,cutoff_at=time_value(data.get('cutoff_at')),
                physical_qty=data.get('physical_qty'),unsellable_qty=data.get('unsellable_qty'),
                expected_version=data.get('expected_version'),request_key=data.get('request_key'),
                reason=data.get('reason'),correction=data.get('correction',False),
                expected_count_version=data.get('expected_count_version'),session=db.session)
        return jsonify(dict(asdict(result),reconciliation_id=task_id)),200 if result.replayed else 201

    @bp.get('/api/inventory/reconciliations')
    @require_role('manager')
    def tasks():
        target=query_store()
        now=_business_now(db.session)
        rows=db.session.execute(db.select(InventoryReconciliation,Product)
            .join(Product,Product.id==InventoryReconciliation.product_id)
            .where(InventoryReconciliation.store_id==target.id)
            .order_by(InventoryReconciliation.id.desc()).limit(100)).all()
        return jsonify(items=[dict(id=t.id,product_id=t.product_id,sku=p.sku,name=p.name,status=t.status,
            version=t.version,source_type=t.source_type,source_id=t.source_id,reason=t.reason,
            created_at=aware(t.created_at),resolved_at=aware(t.resolved_at) if t.resolved_at else None,
            resolved_by=t.resolved_by,resolution=t.resolution,
            responsible_role=(t.resolution or {}).get('responsible_role','manager'),
            due_at=(t.resolution or {}).get('due_at'),
            overdue=t.status=='OPEN' and bool((t.resolution or {}).get('due_at'))
                and datetime.fromisoformat(t.resolution['due_at'])<now) for t,p in rows])

    @bp.get('/api/inventory/movements')
    @require_role('manager')
    def movements():
        target=query_store()
        rows=db.session.execute(db.select(InventoryMovement,Product)
            .join(Product,Product.id==InventoryMovement.product_id)
            .where(InventoryMovement.store_id==target.id)
            .order_by(InventoryMovement.id.desc()).limit(100)).all()
        return jsonify(items=[dict(id=m.id,product_id=m.product_id,sku=p.sku,name=p.name,
            source_type=m.source_type,source_id=m.source_id,physical_delta=m.physical_delta,
            unsellable_delta=m.unsellable_delta,actor_id=m.actor_id,reason=m.reason,
            occurred_at=aware(m.occurred_at),applied_at=aware(m.applied_at),
            inventory_version=m.resulting_version) for m,p in rows])
