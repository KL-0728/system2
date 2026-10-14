"""Local logical backup/empty-target restore; never reset or overwrite live data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from app.config import validate_database

load_dotenv()
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['backup', 'restore', 'verify'])
parser.add_argument('--file', required=True)
parser.add_argument('--source', choices=['demo', 'test'], default='demo')
parser.add_argument('--mysql-bin', default='')
parser.add_argument('--confirm-empty-restore', action='store_true')
args = parser.parse_args()
path = Path(args.file).resolve()
source = os.environ.get('DATABASE_URL' if args.source == 'demo' else 'TEST_DATABASE_URL')
if not source:
    raise SystemExit('Source URL missing')
source_url = validate_database(source, args.source)
if args.action == 'backup':
    url = source_url
else:
    restore = os.environ.get('RESTORE_DATABASE_URL', '')
    url = validate_database(restore, 'test')
    if url.database in {source_url.database, validate_database(os.environ['TEST_DATABASE_URL'], 'test').database,
            validate_database(os.environ['DATABASE_URL'], 'demo').database} or 'restore' not in url.database:
        raise SystemExit('Restore requires an independent system2_*restore*_test database')
engine = create_engine(url)


def manifest():
    with engine.connect() as connection:
        schema = inspect(connection)
        quote = connection.dialect.identifier_preparer.quote
        counts = {name: connection.execute(text(f'SELECT COUNT(*) FROM {quote(name)}')).scalar_one()
            for name in sorted(schema.get_table_names())}
        revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        return {'counts': counts, 'revision': revision}


def command(program):
    executable = str(Path(args.mysql_bin)/program) if args.mysql_bin else shutil.which(program)
    if not executable:
        raise SystemExit('MySQL client not found; supply --mysql-bin')
    return [executable, '--host='+url.host, '--port='+str(url.port or 3306),
        '--user='+url.username, '--default-character-set=utf8mb4']


environment = {**os.environ, 'MYSQL_PWD': url.password or ''}
metadata = path.with_suffix(path.suffix+'.manifest.json')
if args.action == 'backup':
    if path.exists() or metadata.exists():
        raise SystemExit('Refuses overwriting an existing backup')
    path.parent.mkdir(parents=True, exist_ok=True)
    before = manifest()
    with path.open('wb') as destination:
        subprocess.run(command('mysqldump.exe' if os.name=='nt' else 'mysqldump') +
            ['--single-transaction', '--quick', '--no-tablespaces', '--set-gtid-purged=OFF', url.database],
            env=environment, stdout=destination, check=True)
    if before != manifest():
        raise SystemExit('Source changed during backup; pause writes and create a new backup')
    metadata.write_text(json.dumps({**before, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'created_at':datetime.now(timezone.utc).isoformat()}, indent=2), encoding='utf-8')
    print('BACKUP PASS: logical dump and checksum manifest saved (contains private data; do not commit)')
else:
    expected = json.loads(metadata.read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
        raise SystemExit('Backup checksum mismatch')
    if args.action == 'restore':
        if not args.confirm_empty_restore or inspect(engine).get_table_names():
            raise SystemExit('Restore requires explicit flag and an EMPTY independent target')
        with path.open('rb') as source_file:
            subprocess.run(command('mysql.exe' if os.name=='nt' else 'mysql')+[url.database],
                env=environment, stdin=source_file, check=True)
    restored = manifest()
    if any(restored[name] != expected[name] for name in ('counts', 'revision')):
        raise SystemExit('Restore verification failed: table counts or migration differ')
    print('RESTORE VERIFY PASS: checksum, all table counts and migration match; perform business read checks next')
