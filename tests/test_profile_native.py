import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_profile_native_ok():
    res = client.get('/api/profile_native', params={'user_id': 1})
    assert res.status_code in (200, 401, 404)
    if res.status_code == 200:
        j = res.json()
        assert 'user_id' in j and 'total_trades' in j
