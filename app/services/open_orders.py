"""D-owned open-order source for replenishment and order confirmation.

Every physical or promised unit has one source segment.  This reader does not
commit and uses the caller's session so the surrounding store lock protects
the snapshot used by B and C.
"""
from app.contracts import OpenOrdersDTO, OpenSourceDTO, require_utc
from app.extensions import db
from app.models import (Order, OrderItem, Shipment, ShipmentItem,
                        ReplacementAuthorization, ReceiptVariance, ReceiptItem,
                        Store, DeliveryCycle)
from app.services.clock import aware
from app.services.errors import DomainError


def _bucket(eta, expires, disputed, baseline, end, evaluated):
    if disputed or not baseline < eta <= end or eta < evaluated:
        return 'RISK'
    if expires is not None and expires <= evaluated:
        return 'RISK'
    return 'U' if expires is not None else 'C'


class OpenOrdersService:
    def get_open_orders(self, *, store_id, baseline_at, protection_end,
                        evaluated_at, session):
        for value in (baseline_at, protection_end, evaluated_at):
            require_utc(value)
        store = session.get(Store, store_id)
        if store is None:
            raise DomainError('NOT_FOUND', '門市不存在', 404)
        rows = session.execute(db.select(OrderItem, Order).join(Order,
            Order.id == OrderItem.order_id).where(Order.store_id == store_id,
            Order.fixture_only.is_(False)).order_by(OrderItem.id)).all()
        sources = []
        for item, order in rows:
            if item.status in ('REJECTED', 'CANCELLED'):
                continue
            shipments = session.execute(db.select(ShipmentItem).join(Shipment,
                Shipment.id == ShipmentItem.shipment_id).where(
                ShipmentItem.order_item_id == item.id).order_by(ShipmentItem.id)).scalars().all()
            original_shipped = sum(s.shipped_qty for s in shipments if s.kind == 'original')
            if item.committed_qty:
                remaining = max(0, item.committed_qty - original_shipped)
                if remaining:
                    eta = aware(item.eta) if item.eta else aware(order.submitted_at)
                    disputed = bool(item.commitment_disputed)
                    sources.append(OpenSourceDTO('committed', str(item.id), item.product_id,
                        remaining, _bucket(eta, None, disputed, baseline_at,
                            protection_end, evaluated_at), eta, None, disputed))
            elif item.status in ('SUBMITTED', 'CHANGE_PENDING'):
                cycle = session.get(DeliveryCycle, order.cycle_id)
                eta = aware(item.eta) if item.eta else aware(cycle.arrival_at)
                expiry = aware(item.deduction_expires_at)
                sources.append(OpenSourceDTO('pending', str(item.id), item.product_id,
                    item.original_qty, _bucket(eta, expiry, False, baseline_at,
                        protection_end, evaluated_at), eta, expiry, False))
            for line in shipments:
                remaining = line.shipped_qty - line.checked_qty
                if remaining:
                    eta = aware(line.eta)
                    disputed = bool(line.eta_disputed)
                    sources.append(OpenSourceDTO('shipment', str(line.id), item.product_id,
                        remaining, _bucket(eta, None, disputed, baseline_at,
                            protection_end, evaluated_at), eta, None, disputed))
            variances = session.execute(db.select(ReceiptVariance).join(ReceiptItem,
                ReceiptItem.id == ReceiptVariance.receipt_item_id).join(ShipmentItem,
                ShipmentItem.id == ReceiptItem.shipment_item_id).where(
                ShipmentItem.order_item_id == item.id)).scalars().all()
            for variance in variances:
                authorizations = session.execute(db.select(ReplacementAuthorization).where(
                    ReplacementAuthorization.variance_id == variance.id)).scalars().all()
                for auth in authorizations:
                    remaining = auth.authorized_qty - auth.used_qty - auth.closed_qty
                    if remaining:
                        eta = aware(auth.eta)
                        sources.append(OpenSourceDTO('replacement', str(auth.id), item.product_id,
                            remaining, _bucket(eta, None, False, baseline_at,
                                protection_end, evaluated_at), eta, None, False))
        return OpenOrdersDTO(store_id, store.calculation_version, baseline_at,
            protection_end, evaluated_at, tuple(sources))


open_orders_service = OpenOrdersService()
