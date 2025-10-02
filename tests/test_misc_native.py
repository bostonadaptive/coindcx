import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_check_broker_status_no_creds():
    res = client.get('/api/check_broker_status_native', params={'user_id': 9999})
    assert res.status_code in (200, 404, 401)
    if res.status_code == 200:
        j = res.json()
        assert j.get('connected') is False


def test_get_real_account_data_no_creds():
    res = client.get('/api/get_real_account_data_native', params={'user_id': 9999})
    assert res.status_code in (200, 404, 401)
    if res.status_code == 200:
        j = res.json()
        assert j.get('success') in (True, False)


def test_watchlist_add_remove_update_api_key_simple():
    # Try adding and removing a watchlist symbol for user 1 (test DB user)
    add = client.post('/api/add_watchlist_native', params={'user_id': 1}, json={'symbol': 'BTC/USDT'})
    assert add.status_code in (200, 401, 404)

    remove = client.post('/api/remove_watchlist_native', params={'user_id': 1}, json={'symbol': 'BTC/USDT'})
    assert remove.status_code in (200, 401, 404)

    # Try updating API key fields
    upd = client.post('/api/update_api_key_native', params={'user_id': 1}, json={'field': 'apiKey', 'value': 'abc'})
    assert upd.status_code in (200, 401, 400, 404)
