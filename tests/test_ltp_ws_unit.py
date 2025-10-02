import time
import pytest
import importlib

from app import app


def test_ltp_ws_single_label_maps():
    # reload ltp to ensure clean cache
    import ltp
    importlib.reload(ltp)
    key = 'B-ETH_USDT'
    price = 555.5
    try:
        ltp._set_cache_entry(key, {'ts': int(time.time()*1000), 'price': price, 'src': 'ws_price_change'})
    except Exception:
        ltp._LTP_CACHE[key] = {'ts': int(time.time()*1000), 'price': price, 'src': 'ws_price_change'}

    client = app.test_client()
    resp = client.get('/ltp_ws?label=BETHUSDT')
    assert resp.status_code == 200
    js = resp.get_json()
    assert js['label'] == 'BETHUSDT'
    assert js['ltp'] == pytest.approx(price, rel=1e-6)


def test_ltp_ws_missing_label_returns_null():
    import ltp
    importlib.reload(ltp)
    client = app.test_client()
    resp = client.get('/ltp_ws?label=NONEXISTENT')
    assert resp.status_code == 200
    js = resp.get_json()
    assert js['label'] == 'NONEXISTENT'
    assert js['ltp'] is None
