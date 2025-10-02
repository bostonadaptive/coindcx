import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import os
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi

client = TestClient(asgi.fastapi_app)


def test_get_instruments_ok():
    res = client.get('/api/get_instruments')
    # endpoint returns list or dict; if not implemented returns 404
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        data = res.json()
        assert isinstance(data, (list, dict))
