"""Read-only DB/config/schema preflight; never print credentials or reset data."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from alembic.config import Config
from alembic.script import ScriptDirectory
from app import create_app
from app.extensions import db


def check(environment):
    try:
        app = create_app({'APP_ENV': environment, 'MODULE_DEV': '',
            'SQLALCHEMY_ENGINE_OPTIONS': {'pool_pre_ping': True,
                'connect_args': {'connect_timeout': 3}}})
    except (ValueError, SQLAlchemyError) as error:
        # Avoid exception text: invalid URLs can contain secrets.
        print(f'FAIL {environment}: invalid/missing configuration ({type(error).__name__}). Check .env against .env.example.')
        return False
    target = make_url(app.config['SQLALCHEMY_DATABASE_URI'])
    label = f'{environment} {target.host}:{target.port or 3306}/{target.database}'
    with app.app_context():
        try:
            db.session.execute(text('SELECT 1')).scalar_one()
            if not inspect(db.engine).has_table('alembic_version'):
                print(f'FAIL {label}: migrations not applied. Run flask db upgrade with APP_ENV={environment}.')
                return False
            revisions = set(db.session.execute(text('SELECT version_num FROM alembic_version')).scalars())
            config = Config(str(ROOT / 'migrations' / 'alembic.ini'))
            config.set_main_option('script_location', str(ROOT / 'migrations'))
            heads = set(ScriptDirectory.from_config(config).get_heads())
            if revisions != heads:
                print(f'FAIL {label}: schema is not at migration head. Run flask db upgrade with APP_ENV={environment}.')
                return False
            print(f'PASS {label}: connected; migration head {", ".join(sorted(heads))}.')
            return True
        except SQLAlchemyError as error:
            original = getattr(error, 'orig', None)
            args = getattr(original, 'args', ())
            code = args[0] if args and isinstance(args[0], int) else 'unknown'
            if code == 2003:
                action = 'MySQL is not reachable. Start the configured instance before pytest or Flask.'
                if target.host in ('127.0.0.1', 'localhost') and target.port == 3307:
                    action += ' For the existing A checkout, run scripts/start_a_mysql.ps1.'
            elif code == 1045:
                action = 'MySQL rejected authentication. Check the local .env credentials; do not paste passwords into chat.'
            elif code == 1049:
                action = 'Configured database does not exist. Complete the independent DB setup in README.'
            else:
                action = 'Database check failed. Check the MySQL service and migration setup in README.'
            print(f'FAIL {label}: MySQL code {code}. {action}')
            return False
        finally:
            db.session.remove()
            db.engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', choices=('both', 'demo', 'test'), default='both')
    options = parser.parse_args()
    results = [check(env) for env in (('demo', 'test') if options.database == 'both' else (options.database,))]
    raise SystemExit(0 if all(results) else 1)
