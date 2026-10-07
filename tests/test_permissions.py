from app.extensions import db
from app.models import User, Store
from conftest import login


def test_login_csrf_and_cross_store(seeded, client):
    stores = db.session.execute(db.select(Store).order_by(Store.id)).scalars().all()
    assert client.get(f'/api/stores/{stores[0].id}/context').status_code == 401
    assert client.post('/api/auth/login', json={'username': 'manager1', 'password': 'x'}).status_code == 400
    assert login(client, password='wrong-password').status_code == 401
    response = login(client)
    assert response.status_code == 200
    assert client.get(f'/api/stores/{stores[0].id}/context').status_code == 200
    assert client.get(f'/api/stores/{stores[1].id}/context').status_code == 404
    assert client.get('/api/auth/me').json['role'] == 'manager'
    assert client.post('/api/auth/logout').status_code == 400
    assert client.post('/api/auth/logout', headers={'X-CSRFToken': response.json['csrf_token']}).status_code == 200
    assert client.get('/api/auth/me').status_code == 401


def test_disabled_user_and_escaped_template(seeded, client):
    login(client)
    user = db.session.execute(db.select(User).where(User.username == 'manager1')).scalar_one()
    user.active = False
    db.session.flush()
    assert client.get('/api/auth/me').status_code == 401
    assert '示範時間'.encode() in client.get('/login').data


def test_operator_cannot_admin(seeded):
    from app.services.access import authorize_store
    from app.services.errors import DomainError
    import pytest
    user = db.session.execute(db.select(User).where(User.username == 'operator')).scalar_one()
    store = db.session.execute(db.select(Store)).scalars().first()
    with pytest.raises(DomainError) as exc:
        authorize_store(user, store.id, roles=('admin',))
    assert exc.value.status == 403
