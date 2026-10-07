from sqlalchemy import event, inspect, select
from app.services.errors import DomainError


def install_immutable_guards():
    from app.models import (AuditEvent, InventoryMovement, InventoryCountRevision, PolicyVersion,
        ReplenishmentRun, RunItem, FulfillmentEvent, OrderItem, OrderConfirmation)

    def immutable(mapper, connection, target):
        raise DomainError('IMMUTABLE_RECORD', '歷史快照與異動紀錄不得覆寫；請新增修訂', 409)

    for model in (AuditEvent, InventoryMovement, InventoryCountRevision, PolicyVersion,
            ReplenishmentRun, RunItem, FulfillmentEvent):
        event.listen(model, 'before_update', immutable)
        event.listen(model, 'before_delete', immutable)

    @event.listens_for(OrderItem, 'before_update')
    def original_quantity(mapper, connection, target):
        state = inspect(target)
        if any(state.attrs[name].history.has_changes() for name in ('original_qty', 'product_id', 'order_id', 'product_snapshot')):
            immutable(mapper, connection, target)

    @event.listens_for(OrderConfirmation, 'before_update')
    def submitted_confirmation(mapper, connection, target):
        # Binding a preview to an order is allowed once; an already-bound snapshot is frozen.
        previously_bound = connection.execute(select(OrderConfirmation.order_id)
            .where(OrderConfirmation.id == target.id)).scalar_one()
        if previously_bound is not None:
            immutable(mapper, connection, target)

    @event.listens_for(OrderConfirmation, 'before_delete')
    def delete_confirmation(mapper, connection, target):
        if target.order_id is not None:
            immutable(mapper, connection, target)
