"""Probe signed /exchange/ticker with multiple market-name variants to find a format the API accepts.
"""
import json, os, time, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from ltp import _signed_post

variants = [
    'B-ETH_USDT', 'ETH_USDT', 'ETHUSDT', 'B-ETHUSDT', 'ETHINR', 'ETH_INR',
    'BTCUSDT', 'BTC_USDT', 'B-BTC_USDT', 'BTCINR', 'BTC_INR'
]

for v in variants:
    try:
        res = _signed_post('/exchange/ticker', {'market': v}, timeout=6)
    except Exception as e:
        res = {'exception': str(e)}
    print(json.dumps({'variant': v, 'result': res}, default=str, ensure_ascii=False))
    time.sleep(0.2)
