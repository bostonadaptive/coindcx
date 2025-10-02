"""Probe signed GET to /exchange/ticker with different market formats (some servers expect GET with signed body).
"""
import os, json, time
import hmac, hashlib
import requests

API_BASE = os.environ.get('COINDCX_API_BASE') or 'https://api.coindcx.com'
KEY = os.environ.get('COINDCX_API_KEY')
SECRET = os.environ.get('COINDCX_API_SECRET')
variants = ['ETHUSDT','ETH_USDT','B-ETH_USDT','ETHINR','BTCUSDT','BTC_INR']

if not KEY or not SECRET:
    print('missing API key/secret in env')
    raise SystemExit(1)

session = requests.Session()
for v in variants:
    body = {'market': v}
    payload = json.dumps(body, separators=(',',':'))
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    headers = {'Content-Type':'application/json','X-AUTH-APIKEY': KEY,'X-AUTH-SIGNATURE': sig}
    try:
        r = session.get(API_BASE + '/exchange/ticker', data=payload, headers=headers, timeout=8)
        print('variant=',v,'status=',r.status_code,'text=', r.text[:400])
    except Exception as e:
        print('variant=',v,'error=',e)
    time.sleep(0.2)
