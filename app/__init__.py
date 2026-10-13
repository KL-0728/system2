from decimal import Decimal
from uuid import uuid4
from datetime import datetime
from hashlib import sha256
from pathlib import Path
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
    asset_root = Path(app.static_folder)
    asset_versions = {path.relative_to(asset_root).as_posix(): sha256(path.read_bytes()).hexdigest()[:12]
        for path in asset_root.rglob('*') if path.is_file()}
    app.jinja_env.globals['asset_url'] = lambda filename: url_for('static', filename=filename,
        v=asset_versions.get(filename, '1'))
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
        user = getattr(g, 'user', None)
        return {'business_time': business_time, 'module_dev': app.config['MODULE_DEV'],
            'current_user': user, 'navigation_store': next((s for s in user.stores if s.active), None)
                if user and user.role == 'manager' else None}

    @app.after_request
    def response_cache(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return jsonify(status='ok', contract_version='1')

    @app.get('/')
    def home():
        store, drafts, run, tasks = None, [], None, []
        summary = {'orders': 0, 'pending': 0, 'receiving': 0, 'drafts': 0}
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
                summary['drafts'] = db.session.execute(db.select(db.func.count(OrderDraft.id)).where(
                    OrderDraft.user_id == g.user.id, OrderDraft.store_id == store.id,
                    OrderDraft.status == 'DRAFT')).scalar_one()
        if g.user:
            from app.models import Order, Store, OperationalTask
            order_query = db.select(Order.status, db.func.count(Order.id)).join(Store,
                Store.id == Order.store_id).where(Store.active.is_(True), Order.fixture_only.is_(False))
            if store:
                order_query = order_query.where(Order.store_id == store.id)
            elif g.user.role == 'manager':
                order_query = order_query.where(db.false())
            statuses = dict(db.session.execute(order_query.group_by(Order.status)).all())
            summary.update(orders=sum(statuses.values()), pending=statuses.get('SUBMITTED', 0)
                + statuses.get('CHANGE_PENDING', 0), receiving=sum(statuses.get(key, 0)
                for key in ('SHIPPED', 'PARTIALLY_SHIPPED', 'PARTIALLY_RECEIVED')))
            if g.user.role == 'operator':
                from app.services.clock import aware
                now = business_now()
                rows = db.session.execute(db.select(OperationalTask).join(Store,
                    Store.id == OperationalTask.store_id).where(Store.active.is_(True),
                    OperationalTask.owner_role == 'operator', OperationalTask.completed_at.is_(None))
                    .order_by(OperationalTask.due_at, OperationalTask.id)).scalars().all()
                tasks = [dict(type=row.task_type, due_at=aware(row.due_at).isoformat(),
                    overdue=aware(row.due_at) < now, store_id=row.store_id) for row in rows]
        return render_template('home.html', store=store, drafts=drafts, run=run, tasks=tasks,
            summary=summary, ordering_available='runs' in app.extensions['service_providers'])

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
