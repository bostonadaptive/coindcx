import os
import time
import json
from importlib import reload

import pytest

from app import app as flask_app


@pytest.fixture(autouse=True)
def disable_aggregator_env(monkeypatch):
    # Prevent background aggregator/pollers from starting during tests
    monkeypatch.setenv('DISABLE_LTP_AGG', '1')
    # Ensure debug prints don't pollute test output
    monkeypatch.setenv('LTP_DEBUG_PRINT', '0')
    yield


def test_ltp_ws_normalization_matches_cache():
    # Import ltp module and ensure fresh module (so we can access _LTP_CACHE/_set_cache_entry)
    import ltp
    reload(ltp)

    # Populate the centralized cache with a variant key 'B-ETH_USDT'
    key = 'B-ETH_USDT'
    price = 1234.56
    # Use the helper if available, otherwise set directly
    try:
        ltp._set_cache_entry(key, {'ts': int(time.time()*1000), 'price': price, 'src': 'ws_price_change'})
    except Exception:
        ltp._LTP_CACHE[key] = {'ts': int(time.time()*1000), 'price': price, 'src': 'ws_price_change'}

    # Use Flask test client to call /ltp_ws with normalized alphanumeric label BETHUSDT
    client = flask_app.test_client()
    resp = client.get('/ltp_ws?label=BETHUSDT')
    assert resp.status_code == 200
    js = resp.get_json()
    assert js is not None
    # endpoint returns {'label': 'BETHUSDT', 'ltp': <val>} for single label
    assert 'label' in js and js['label'] == 'BETHUSDT'
    assert 'ltp' in js
    assert js['ltp'] == pytest.approx(price, rel=1e-6)
