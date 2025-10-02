import sys
proj = r"D:\Backup\My Projects\CoinDCX\webApp"
if proj not in sys.path:
    sys.path.insert(0, proj)

import asgi
from types import SimpleNamespace
import asyncio
import os
# Ensure test helper routes are enabled before importing the app
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi
import os
# Ensure test helper routes are enabled before importing the app/module
os.environ['ASGI_ENABLE_TEST_HELPERS'] = '1'
from fastapi.testclient import TestClient
import asgi


client = TestClient(asgi.fastapi_app)


def test_get_watchlist():
    res = client.get('/api/get_watchlist', params={'user_id': 1})
    assert res.status_code == 200
    assert res.json() is not None


def test_get_paper_wallet():
    res = client.get('/api/get_paper_wallet', params={'user_id': 1})
    assert res.status_code in (200, 404)


def test_get_positions():
    res = client.get('/api/get_positions', params={'user_id': 1})
    assert res.status_code == 200


def test_check_broker_status():
    res = client.get('/api/check_broker_status', params={'user_id': 1})
    assert res.status_code == 200


def test_get_real_account_data():
    res = client.get('/api/get_real_account_data', params={'user_id': 1})
    assert res.status_code in (200, 404)
