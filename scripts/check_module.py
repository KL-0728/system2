"""Read-only smoke for a selected module; never invent business success."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from app import create_app

module = sys.argv[1] if len(sys.argv) == 2 else ''
if module not in ('B', 'C', 'D'):
    raise SystemExit('Usage: python scripts/check_module.py B|C|D')
app = create_app({'MODULE_DEV': module})
if app.config['APP_ENV'] != 'demo':
    raise SystemExit('Smoke requires your local demo DB')
client = app.test_client()
token = client.get('/api/auth/csrf').json['csrf_token']
username = 'operator' if module == 'D' else 'manager1'
response = client.post('/api/auth/login', json={'username': username, 'password': os.getenv('DEMO_PASSWORD')},
    headers={'X-CSRFToken': token})
assert response.status_code == 200, f'Login status: {response.status_code}'
response = client.get(f'/modules/{module.lower()}/')
assert response.status_code == 200, f'Module status: {response.status_code}'
assert '非真實跨模組整合'.encode() in response.data
assert client.get('/health').json['status'] == 'ok'
assert client.get('/modules/x/').status_code == 404
print(f'{module}: health/login/module page 200; unselected module 404; explicit test-provider banner present.')
