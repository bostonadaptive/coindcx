"""Test multiple market name variants against signed and unsigned /exchange/ticker endpoints.

Usage: python scripts\test_ticker_variants.py
"""
import os
import json
import time
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ltp import _signed_post, session

variants = [
    'B-ETH_USDT',
    'ETH_USDT',
    'ETHUSDT',
    'B-ETHUSDT',
    'B-ETH_USDT'.replace('_',''),
    'B-ETH_USDT'.replace('-',''),
]

print('Testing variants:', variants)
for v in variants:
    try:
        s = _signed_post('/exchange/ticker', {'market': v}, timeout=5)
    except Exception as e:
        s = f'exception: {e}'
    try:
        r = session.post((os.environ.get('COINDCX_API_BASE') or 'https://api.coindcx.com') + '/exchange/ticker', json={'market': v}, timeout=6)
        try:
            u = r.json()
        except Exception:
            u = r.text
    except Exception as e:
        u = f'exception: {e}'
    print(json.dumps({'variant': v, 'signed': s, 'unsigned': u}, default=str, ensure_ascii=False))
    time.sleep(0.2)
