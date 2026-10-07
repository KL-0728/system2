import importlib
from flask import current_app
from app.services.errors import DomainError

SLOTS = ('open_orders', 'runs', 'integrity', 'inventory_writer', 'fulfillment', 'orders')
MODULES = ('inventory', 'ordering', 'fulfillment')


def register_provider(name, provider, *, test_only=False):
    if name not in SLOTS:
        raise ValueError('未知服務插槽')
    if test_only and current_app.config['APP_ENV'] != 'test' and not current_app.config['MODULE_DEV']:
        raise ValueError('測試供應者僅允許 test／明示模組開發模式')
    current_app.extensions['service_providers'][name] = (provider, test_only)


def get_provider(name):
    found = current_app.extensions['service_providers'].get(name)
    if not found:
        raise DomainError('SERVICE_UNAVAILABLE', f'尚未接入 {name} 真實服務', 503)
    provider, test_only = found
    if test_only and current_app.config['APP_ENV'] != 'test' and not current_app.config['MODULE_DEV']:
        raise DomainError('SERVICE_UNAVAILABLE', '此環境禁止測試供應者', 503)
    return provider


def initialize_providers(app):
    app.extensions['service_providers'] = {}
    with app.app_context():
        # Every owner maintains their own installer, avoiding shared registration edits.
        for module in MODULES:
            importlib.import_module(f'app.modules.{module}.services').install()
        if app.config['MODULE_DEV']:
            from app.testing.providers import install_test_providers
            install_test_providers(app.config['MODULE_DEV'])
