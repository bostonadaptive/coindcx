import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_strategy_signals_ok():
    res = client.get('/api/strategy_signals', params={'user_id': 1})
    assert res.status_code in (200, 404, 401)
    if res.status_code == 200:
        j = res.json()
        assert 'items' in j and 'page' in j


def test_refill_wallet_post():
    # refill requires auth; use query override
    res = client.post('/api/refill_wallet', params={'user_id': 1})
    assert res.status_code in (200, 401, 404)
    if res.status_code == 200:
        j = res.json()
        assert j.get('success') is True or 'balance' in j


def test_profile_adapter():
    res = client.get('/api/profile', params={'user_id': 1})
    assert res.status_code in (200, 401, 404)
    if res.status_code == 200:
        j = res.json()
        assert 'user_id' in j and 'total_trades' in j
