import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_get_balance_no_creds():
    res = client.get('/api/get_balance_native', params={'user_id': 9999})
    assert res.status_code == 200
    j = res.json()
    assert j.get('connected') is False


def test_get_balance_for_user_1():
    # user 1 exists in test DB and helper returns a dict; endpoint should return connected bool
    res = client.get('/api/get_balance_native', params={'user_id': 1})
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        j = res.json()
        assert 'connected' in j
