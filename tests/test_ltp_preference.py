import os
import importlib
import time

# ensure tests import local project
import pytest


def reload_ltp_with_env(pref_futures: bool):
    # set env and reload module
    os.environ['COINDCX_PREFER_FUTURES'] = '1' if pref_futures else '0'
    # Force a fresh import so module-level COINDCX_PREFER_FUTURES is re-evaluated
    import sys
    if 'ltp' in sys.modules:
        del sys.modules['ltp']
    import ltp as ltp_mod
    importlib.reload(ltp_mod)
    return ltp_mod


def test_prefer_futures_over_spot_by_default_false():
    ltp = reload_ltp_with_env(False)
    # clear cache
    ltp._LTP_CACHE.clear()
    now_ms = int(time.time() * 1000)
    # spot entry recent
    ltp._set_cache_entry('BTCUSDT', {'ts': now_ms, 'price': 100.0, 'src': 'ws_currentPrices:spot'})
    # futures entry older (store under a different normalized key the aggregator would write)
    ltp._set_cache_entry('B-BTC_USDT', {'ts': now_ms - 60000, 'price': 200.0, 'src': 'ws_currentPrices:derivatives'})
    # last_price_usdt should return the recent spot price when preference is off
    val = ltp.last_price_usdt('BTCUSDT', ttl=2.0, force_refresh=False)
    assert val == 100.0


def test_prefer_futures_when_toggle_true():
    ltp = reload_ltp_with_env(True)
    ltp._LTP_CACHE.clear()
    now_ms = int(time.time() * 1000)
    # spot entry recent
    ltp._set_cache_entry('BTCUSDT', {'ts': now_ms, 'price': 100.0, 'src': 'ws_currentPrices:spot'})
    # futures entry older (store under market form)
    ltp._set_cache_entry('B-BTC_USDT', {'ts': now_ms - 60000, 'price': 200.0, 'src': 'ws_currentPrices:derivatives'})
    val = ltp.last_price_usdt('BTCUSDT', ttl=2.0, force_refresh=False)
    # preference true -> choose futures price (200)
    assert val == 200.0
