import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_get_watchlist_for_user_1():
    res = client.get('/api/get_watchlist_native', params={'user_id': 1})
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        j = res.json()
        assert isinstance(j, list)


def test_get_positions_for_user_1():
    res = client.get('/api/get_positions_native', params={'user_id': 1})
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        j = res.json()
        # Accept either new shape {'positions': [...]} or legacy {'open': [...], 'closed': [...]} or list
        assert ('positions' in j) or (isinstance(j, dict) and ('open' in j and 'closed' in j)) or isinstance(j, list)
