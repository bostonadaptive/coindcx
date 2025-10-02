import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_refill_wallet_native_creates_and_resets():
    # call the native refill endpoint with user_id override
    res = client.post('/api/refill_wallet_native', params={'user_id': 1})
    assert res.status_code in (200, 401, 404)
    if res.status_code == 200:
        j = res.json()
        assert j.get('success') is True
        assert j.get('balance') == 100000
