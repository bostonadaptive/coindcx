import os, sys, time
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    import ltp
except Exception as e:
    print('failed to import ltp:', e)
    raise

pair = 'B-ETH_USDT'
print('calling last_price_usdt for', pair)
px = ltp.last_price_usdt(pair, force_refresh=True)
print('last_price_usdt returned:', px)
print('\n_cache snapshot size:', len(ltp.get_ltp_cache_snapshot()))
for k, v in ltp.get_ltp_cache_snapshot().items():
    print(k, '=>', v)

# Also print raw _LTP_CACHE keys
try:
    print('\n_raw _LTP_CACHE keys:', list(ltp._LTP_CACHE.keys()))
except Exception:
    pass
