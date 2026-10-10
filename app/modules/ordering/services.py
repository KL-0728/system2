from app.providers import register_provider
from app.services.orders import ordering_service


def install():
    # C owns the real immutable-order reader consumed by D.
    register_provider('orders', ordering_service)
