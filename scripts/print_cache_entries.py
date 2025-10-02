import os, sys, time
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    import ltp
except Exception as e:
    print('failed to import ltp:', e); raise

pairs = ['B-ETH_USDT','ETHUSDT','ETH_USDT','BETHUSDT','b-eth_usdt']
for p in pairs:
    entry = ltp._get_cache_entry(p.upper())
    print(p, '->', entry)

# also print all keys in snapshot
snap = ltp.get_ltp_cache_snapshot()
print('\nSnapshot keys count:', len(snap))
for k in sorted(list(snap.keys()))[:30]:
    print(k, '=>', snap[k])
