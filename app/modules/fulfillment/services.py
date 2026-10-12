from app.providers import register_provider
from app.services.fulfillment import fulfillment_service
from app.services.open_orders import open_orders_service
from app.services import tasks  # registers order-item task creation in the caller's transaction


def install():
    register_provider('open_orders', open_orders_service)
    register_provider('fulfillment', fulfillment_service)
