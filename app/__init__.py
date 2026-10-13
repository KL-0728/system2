from decimal import Decimal
from uuid import uuid4
from datetime import datetime
from flask import Flask, g, jsonify, render_template, request, redirect, url_for
from flask.json.provider import DefaultJSONProvider
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError
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
    from app.routes.management import bp as management_bp
    app.register_blueprint(management_bp)

    @app.before_request
    def before():
        g.request_id = str(uuid4())
        load_user()

    @app.errorhandler(DomainError)
    def domain_error(error):
        db.session.rollback()
        # HTML form failures stay actionable; JSON clients retain the API contract.
        login_form = request.endpoint == 'auth.login' and not request.is_json
        if login_form:
            from app.routes.auth import safe_next
            messages = {'HTTP_429': '登入嘗試過於頻繁，請稍候一分鐘再試。'}
            try:
                form = request.form
            except HTTPException:
                form = {}  # Oversized/malformed bodies must not fail again during recovery.
            username = form.get('username', '')[:80]
            return render_template('auth/login.html', login_error=messages.get(error.code, error.message),
                username=username, next_url=safe_next(form.get('next'))), error.status
        browser_page = (request.method == 'GET' and not request.path.startswith('/api/')
            and request.accept_mimetypes.best_match(['text/html', 'application/json']) == 'text/html')
        if browser_page and error.code == 'UNAUTHENTICATED':
            return redirect(url_for('auth.login_page', next=request.full_path.rstrip('?')))
        if browser_page:
            return render_template('error.html', message=error.message,
                request_id=getattr(g, 'request_id', '')), error.status
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
        business_time = None
        if app.config['APP_ENV'] != 'production':
            try:
                business_time = business_now().astimezone(TAIPEI)
            except (DomainError, SQLAlchemyError):
                db.session.rollback()  # Recovery pages must survive clock/DB unavailability.
        return {'business_time': business_time, 'module_dev': app.config['MODULE_DEV'],
            'current_user': getattr(g, 'user', None)}

    @app.get('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status='ok', contract_version='1')

    @app.get('/')
    def home():
        store, drafts, run, tasks = None, [], None, []
        if g.user and g.user.role in ('manager', 'admin'):
            from app.models import Store, OrderDraft
            from app.services.run_sources import latest_run
            store = next((s for s in g.user.stores if s.active), None) if g.user.role == 'manager' else \
                db.session.execute(db.select(Store).where(Store.active.is_(True)).order_by(Store.id).limit(1)).scalar_one_or_none()
            if store:
                from app.services.tasks import list_tasks
                tasks = list_tasks(db.session, store.id, g.user.role)
                run = latest_run(store.id)
                drafts = db.session.execute(db.select(OrderDraft).where(OrderDraft.user_id == g.user.id,
                    OrderDraft.store_id == store.id, OrderDraft.status == 'DRAFT').order_by(
                    OrderDraft.updated_at.desc()).limit(5)).scalars().all()
        return render_template('home.html', store=store, drafts=drafts, run=run, tasks=tasks,
            ordering_available='runs' in app.extensions['service_providers'])

    @app.get('/api/stores/<int:store_id>/context')
    @require_role()
    def store_context(store_id):
        store = authorize_store(g.user, store_id)
        return jsonify(id=store.id, code=store.code, calculation_version=store.calculation_version)

    from app.cli import register_cli
    register_cli(app)
    from app.providers import initialize_providers, MODULES
    from importlib import import_module
    initialize_providers(app)
    for module in MODULES:
        app.register_blueprint(import_module(f'app.modules.{module}.routes').bp)
    from app.routes.module_dev import bp as dev_bp
    app.register_blueprint(dev_bp)
    return app
