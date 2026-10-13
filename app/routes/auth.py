from flask import Blueprint, g, jsonify, request, session, render_template, redirect, url_for
from flask_wtf.csrf import generate_csrf
from app.extensions import db, limiter
from app.models.identity import User
from app.services.access import require_role
from app.services.errors import DomainError
from urllib.parse import urlsplit

bp = Blueprint('auth', __name__)


def safe_next(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//') or '\\' in value:
        return url_for('home')
    try:
        parsed = urlsplit(value)
    except ValueError:
        return url_for('home')
    if parsed.scheme or parsed.netloc or any(ord(char) < 32 for char in value):
        return url_for('home')
    return value


@bp.get('/login')
def login_page():
    return render_template('auth/login.html', next_url=safe_next(request.args.get('next')))


@bp.get('/api/auth/csrf')
def token():
    return jsonify(csrf_token=generate_csrf())


@bp.post('/api/auth/login')
@limiter.limit('5 per minute')
def login():
    data = request.get_json(silent=True) if request.is_json else request.form
    if request.is_json and not isinstance(data, dict):
        raise DomainError('INVALID_INPUT', '請提供包含帳號與密碼的資料物件', 400)
    username, password = data.get('username'), data.get('password')
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
        raise DomainError('INVALID_INPUT', '請輸入帳號與密碼', 400)
    user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
    if not user or not user.active or not user.check_password(password):
        raise DomainError('INVALID_CREDENTIALS', '帳號或密碼錯誤', 401)
    session.clear()
    session['user_id'] = user.id
    session['credential_token'] = user.session_token()
    g.pop('csrf_token', None)
    if request.is_json:
        return jsonify(user={'id': user.id, 'role': user.role}, csrf_token=generate_csrf())
    return redirect(safe_next(data.get('next')))


@bp.post('/logout')
@bp.post('/api/auth/logout')
@require_role()
def logout():
    session.clear()
    if request.path == '/logout':
        return redirect(url_for('auth.login_page'))
    return jsonify(ok=True)


@bp.get('/api/auth/me')
@require_role()
def me():
    return jsonify(id=g.user.id, username=g.user.username, role=g.user.role,
        stores=[{'id': s.id, 'code': s.code} for s in g.user.stores if s.active])
