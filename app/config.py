import os
from sqlalchemy.engine import make_url


def validate_database(url, environment):
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql':
        raise ValueError('資料庫必須使用 mysql+pymysql／InnoDB')
    name = parsed.database or ''
    suffix = {'test': '_test', 'demo': '_demo'}.get(environment)
    if suffix and (not name.startswith('system2_') or not name.endswith(suffix)):
        raise ValueError(f'{environment} DB 必須為 system2_*{suffix}')
    if environment in ('demo', 'test') and parsed.host not in ('127.0.0.1', 'localhost'):
        raise ValueError('demo／test 僅允許本機資料庫')
    return parsed


def settings(overrides=None):
    overrides = overrides or {}
    env = overrides.get('APP_ENV', os.getenv('APP_ENV', 'demo'))
    if env not in ('demo', 'test', 'production'):
        raise ValueError('APP_ENV 必須為 demo／test／production')
    database = overrides.get('SQLALCHEMY_DATABASE_URI') or os.getenv(
        'TEST_DATABASE_URL' if env == 'test' else 'DATABASE_URL')
    if not database:
        raise ValueError('請設定 DATABASE_URL／TEST_DATABASE_URL')
    parsed = validate_database(database, env)
    if env == 'test':
        demo = os.getenv('DATABASE_URL')
        if demo:
            other = make_url(demo)
            if (parsed.host, parsed.port or 3306, parsed.database) == (other.host, other.port or 3306, other.database):
                raise ValueError('測試與 demo DB 不得相同')
    secret = overrides.get('SECRET_KEY') or os.getenv('SECRET_KEY')
    if not secret or len(secret) < 32 or secret.startswith('REPLACE_'):
        raise ValueError('SECRET_KEY 至少32字元，請自行產生並放於 .env')
    module = overrides.get('MODULE_DEV', os.getenv('MODULE_DEV', ''))
    if module not in ('', 'B', 'C', 'D') or (module and env == 'production'):
        raise ValueError('模組開發模式僅限 demo／test，MODULE_DEV=B／C／D')
    result = dict(APP_ENV=env, TESTING=env == 'test', SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=database, SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True}, MODULE_DEV=module,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=env == 'production', MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        DEBUG=False, RATELIMIT_ENABLED=True)
    result.update(overrides)
    if env == 'production' and (result.get('DEBUG') or not result.get('WTF_CSRF_ENABLED', True)
            or not result.get('SESSION_COOKIE_SECURE') or result.get('TESTING')):
        raise ValueError('正式環境不得停用安全設定')
    return result
