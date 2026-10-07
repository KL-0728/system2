import os
import pytest
from dotenv import load_dotenv
from app import create_app
from app.extensions import db
from app.config import validate_database

load_dotenv()


@pytest.fixture
def app():
    # Fail closed: never fall back to the demo connection or SQLite.
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.fail('TEST_DATABASE_URL 未設定，拒絕測試／清理')
    validate_database(url, 'test')
    application = create_app({'APP_ENV': 'test', 'SQLALCHEMY_DATABASE_URI': url,
        'SECRET_KEY': 'test-only-secret-key-at-least-32-characters', 'RATELIMIT_ENABLED': False,
        'MODULE_DEV': ''})
    with application.app_context():
        # DDL is managed by migrations. Tests use an isolated outer transaction.
        connection = db.engine.connect()
        outer = connection.begin()
        db.session.remove()
        old_engines = dict(db.engines)
        db.engines[None] = connection
        try:
            yield application
        finally:
            db.session.remove()
            if outer.is_active:
                outer.rollback()
            db.engines.update(old_engines)
            connection.close()
    


@pytest.fixture
def seeded(app, monkeypatch):
    monkeypatch.setenv('DEMO_PASSWORD', 'Synthetic-test-password-2026')
    from app.seed import seed_demo
    seed_demo()
    db.session.commit()  # Release fixture savepoint; outer test transaction remains isolated.
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username='manager1', password='Synthetic-test-password-2026'):
    token = client.get('/api/auth/csrf').json['csrf_token']
    response = client.post('/api/auth/login', json={'username': username, 'password': password},
        headers={'X-CSRFToken': token})
    return response
