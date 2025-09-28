# Small smoke-test script to query key endpoints and print status + content-type
import requests

BASE = 'http://127.0.0.1:5000'
ENDPOINTS = ['/trade_history/export','/trade_history/refresh','/paper_history','/get_real_wallet']

for ep in ENDPOINTS:
    url = BASE + ep
    try:
        r = requests.get(url, allow_redirects=False, timeout=10)
        ct = r.headers.get('content-type')
        print(ep, r.status_code, ct)
        body = r.text[:800].replace('\n',' ')
        print('BODY:', body)
    except Exception as e:
        print(ep, 'ERROR', e)
