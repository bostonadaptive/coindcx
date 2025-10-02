import os, time, importlib, sys
# ensure project root on sys.path
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ['COINDCX_PREFER_FUTURES']='1'
import ltp as ltp
importlib.reload(ltp)
ltp._LTP_CACHE.clear()
now_ms=int(time.time()*1000)
ltp._set_cache_entry('BTCUSDT', {'ts': now_ms, 'price':100.0, 'src':'ws_currentPrices:spot'})
ltp._set_cache_entry('B-BTC_USDT', {'ts': now_ms-60000, 'price':200.0, 'src':'ws_currentPrices:derivatives'})
print('cache keys:', list(ltp._LTP_CACHE.keys()))
# attempt to call last_price_usdt
print('last_price_usdt ->', ltp.last_price_usdt('BTCUSDT', ttl=2.0, force_refresh=False))
# inspect _get_cache_entry on candidate keys
def normalize(pair_in):
    p=(pair_in or '').upper()
    if p.startswith('B-'):
        market_b=p
    else:
        if '_' in p:
            body=p.replace('-', '').replace('/', '')
            if not body.startswith('B-') and not body.startswith('B'):
                if body.startswith('B'):
                    market_b='B-'+body[1:]
                else:
                    market_b='B-'+body
            else:
                market_b=body
        else:
            if p.endswith('USDT'):
                base=p[:-4]; quote='USDT'
            else:
                base=p[:-3]; quote=p[-3:]
            market_b=f'B-{base}_{quote}'
    raw=market_b[2:].replace('_','') if market_b.startswith('B-') else market_b.replace('_','')
    return market_b, raw
mb, raw = normalize('BTCUSDT')
keys=[ 'BTCUSDT', mb, raw, raw.replace('_',''), mb.replace('B-',''), 'BTCUSDT'.replace('B-','')]
print('candidate keys:', keys)
for k in keys:
    print(k, '->', ltp._get_cache_entry(k))
