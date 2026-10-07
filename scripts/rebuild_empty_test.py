"""Explicit safe schema reconstruction only for an EMPTY configured local test DB."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from app import create_app
from app.extensions import db
from app.config import validate_database
from sqlalchemy import inspect, text

if sys.argv[1:] != ['--confirm-empty-test']:
    raise SystemExit('Requires --confirm-empty-test; refuses nonempty databases.')
app = create_app({'APP_ENV': 'test', 'MODULE_DEV': ''})
with app.app_context():
    target = validate_database(app.config['SQLALCHEMY_DATABASE_URI'], 'test')
    tables = inspect(db.engine).get_table_names()
    for table in tables:
        if table != 'alembic_version':
            quoted = db.engine.dialect.identifier_preparer.quote(table)
            if db.session.execute(text(f'SELECT COUNT(*) FROM {quoted}')).scalar_one():
                raise SystemExit('Nonempty test DB: refuses schema reconstruction.')
    print(f'Confirmed EMPTY local test DB: {target.database}; reconstructing migration chain.')
    # Explicit opt-in reconstruction, not normal pytest cleanup. Remove FKs first so
    # cycles and MySQL FK-owned indexes do not depend on downgrade implementation.
    schema = inspect(db.engine)
    foreign_keys = [(table, fk['name']) for table in tables for fk in schema.get_foreign_keys(table)]
    db.session.rollback()
    with db.engine.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote
        for table, name in foreign_keys:
            connection.exec_driver_sql(f'ALTER TABLE {quote(table)} DROP FOREIGN KEY {quote(name)}')
        for table in tables:
            connection.exec_driver_sql(f'DROP TABLE {quote(table)}')
environment = {**os.environ, 'APP_ENV': 'test', 'MODULE_DEV': ''}
for command in [('upgrade',), ('check',), ('heads',)]:
    subprocess.run([sys.executable, '-m', 'flask', '--app', 'wsgi', 'db', *command], env=environment, check=True)
