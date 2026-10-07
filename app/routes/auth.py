from flask import Blueprint, g, jsonify, request, session, render_template, redirect, url_for
from flask_wtf.csrf import generate_csrf
from app.extensions import db, limiter
from app.models.identity import User
from app.services.access import require_role
from app.services.errors import DomainError

bp = Blueprint('auth', __name__)


@bp.get('/login')
def login_page():
    return render_template('auth/login.html')


@bp.get('/api/auth/csrf')
def token():
    return jsonify(csrf_token=generate_csrf())


@bp.post('/api/auth/login')
@limiter.limit('5 per minute')
def login():
    data = request.get_json(silent=True) or request.form
    username, password = data.get('username'), data.get('password')
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
        raise DomainError('INVALID_INPUT', '請輸入帳號與密碼', 400)
    user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
    if not user or not user.active or not user.check_password(password):
        raise DomainError('INVALID_CREDENTIALS', '帳號或密碼錯誤', 401)
    session.clear()
    session['user_id'] = user.id
    g.pop('csrf_token', None)
    if request.is_json:
        return jsonify(user={'id': user.id, 'role': user.role}, csrf_token=generate_csrf())
    return redirect(url_for('home'))


@bp.post('/api/auth/logout')
@require_role()
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get('/api/auth/me')
@require_role()
def me():
    return jsonify(id=g.user.id, username=g.user.username, role=g.user.role,
        stores=[{'id': s.id, 'code': s.code} for s in g.user.stores if s.active])
