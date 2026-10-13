"""Operational navigation, real dashboard counts and cache-safe assets."""
import re
from hashlib import sha256
from pathlib import Path
from test_management import login
from test_full_integration import real_order


def test_login_assets_and_password_control_are_current(seeded, client):
    response=client.get('/login')
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    html=response.get_data(as_text=True)
    assert 'auth-layout' in html and 'data-password-toggle="password"' in html
    assert '本機種子' not in html and '測試系統' not in html
    version=sha256((Path(seeded.static_folder)/'css/operations.css').read_bytes()).hexdigest()[:12]
    assert f'operations.css?v={version}' in html
    assert 'password-visibility.js?v=' in html
    assert '示範環境' in html and '示範時間' in html
    seeded.config['APP_ENV']='production'
    production=client.get('/login').get_data(as_text=True)
    assert '示範環境' not in production and '示範時間' not in production


def test_dashboard_counts_and_navigation_are_scoped_to_role_and_store(seeded, client):
    order, _, _, _, _=real_order(seeded,client)
    first=client.get('/').get_data(as_text=True)
    assert '待回覆訂單</small><strong>1</strong>' in first
    assert '管理設定' not in first
    assert len(re.findall('aria-label="店長主選單"',first))==1
    assert login(client,'manager2').status_code==200
    other=client.get('/').get_data(as_text=True)
    assert '待回覆訂單</small><strong>0</strong>' in other
    assert order.number not in other
    assert login(client,'operator').status_code==200
    operator=client.get('/').get_data(as_text=True)
    assert '待回覆訂單</small><strong>1</strong>' in operator
    assert '待處理事項</small><strong>10</strong>' in operator
    assert '管理設定' not in operator and '前往接單履約' in operator
    assert login(client,'admin').status_code==200
    assert '管理設定' in client.get('/admin').get_data(as_text=True)


def test_json_and_authenticated_pages_are_not_cached(seeded,client):
    assert login(client).status_code==200
    for url in ('/','/store/ordering','/api/auth/me','/api/ordering/acknowledgement'):
        response=client.get(url)
        assert response.status_code==200
        assert response.headers['Cache-Control']=='no-store'
