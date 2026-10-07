from decimal import Decimal
from uuid import uuid4
from datetime import datetime
from flask import Flask, g, jsonify, render_template
from flask.json.provider import DefaultJSONProvider
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException
from app.config import settings
from app.extensions import db, migrate, csrf, limiter


class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError('非有限 Decimal 不可序列化')
            return format(value, 'f')
        if isinstance(value, datetime):
            from app.services.clock import aware
            return aware(value).isoformat()
        return DefaultJSONProvider.default(value)


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.update(settings(overrides))
    app.json = JSONProvider(app)
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    from app import models
    from app.routes.auth import bp
    from app.services.access import load_user, require_role, authorize_store
    from app.services.errors import DomainError
    from app.services.clock import business_now, TAIPEI
    app.register_blueprint(bp)

    @app.before_request
    def before():
        g.request_id = str(uuid4())
        load_user()

    @app.errorhandler(DomainError)
    def domain_error(error):
        db.session.rollback()
        return jsonify(error={'code': error.code, 'message': error.message,
            'details': error.details, 'request_id': getattr(g, 'request_id', '')}), error.status

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return domain_error(DomainError('CSRF_FAILED', '安全驗證失敗，請重新載入', 400))

    @app.errorhandler(HTTPException)
    def http_error(error):
        return domain_error(DomainError(f'HTTP_{error.code}', error.name, error.code))

    @app.errorhandler(Exception)
    def server_error(error):
        app.logger.exception('Request failed')
        return domain_error(DomainError('INTERNAL_ERROR', '操作失敗，請提供請求編號', 500))

    @app.context_processor
    def context():
        return {'business_time': business_now().astimezone(TAIPEI) if app.config['APP_ENV'] != 'production'
            else None, 'module_dev': app.config['MODULE_DEV'], 'current_user': getattr(g, 'user', None)}

    @app.get('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status='ok', contract_version='1')

    @app.get('/')
    def home():
        return render_template('home.html')

    @app.get('/api/stores/<int:store_id>/context')
    @require_role()
    def store_context(store_id):
        store = authorize_store(g.user, store_id)
        return jsonify(id=store.id, code=store.code, calculation_version=store.calculation_version)

    from app.cli import register_cli
    register_cli(app)
    return app
