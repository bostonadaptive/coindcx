import os
import importlib
import time

import pytest


def reload_ltp_force(env_on: bool):
    os.environ['COINDCX_FORCE_FUTURES'] = '1' if env_on else '0'
    # ensure soft-preference is disabled during these force tests to avoid interference
    os.environ['COINDCX_PREFER_FUTURES'] = '0'
    import sys
    if 'ltp' in sys.modules:
        del sys.modules['ltp']
    import ltp as ltp_mod
    importlib.reload(ltp_mod)
    return ltp_mod


def test_force_futures_over_spot():
    ltp = reload_ltp_force(True)
    ltp._LTP_CACHE.clear()
    now_ms = int(time.time() * 1000)
    # spot recent
    ltp._set_cache_entry('BTCUSDT', {'ts': now_ms, 'price': 100.0, 'src': 'ws_currentPrices:spot'})
    # futures older
    ltp._set_cache_entry('B-BTC_USDT', {'ts': now_ms - 60000, 'price': 200.0, 'src': 'ws_currentPrices:derivatives'})
    val = ltp.last_price_usdt('BTCUSDT', ttl=2.0, force_refresh=False)
    assert val == 200.0


def test_force_toggle_off_behaviour():
    ltp = reload_ltp_force(False)
    ltp._LTP_CACHE.clear()
    now_ms = int(time.time() * 1000)
    ltp._set_cache_entry('BTCUSDT', {'ts': now_ms, 'price': 100.0, 'src': 'ws_currentPrices:spot'})
    ltp._set_cache_entry('B-BTC_USDT', {'ts': now_ms - 60000, 'price': 200.0, 'src': 'ws_currentPrices:derivatives'})
    val = ltp.last_price_usdt('BTCUSDT', ttl=2.0, force_refresh=False)
    assert val == 100.0
