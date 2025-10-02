import requests, time, os
ROOT = os.path.dirname(os.path.dirname(__file__))
BASE = os.environ.get('APP_BASE','http://127.0.0.1:5000')
labels = ['BETHUSDT','B-ETH_USDT','ETHUSDT','BTCUSDT','B-BTC_USDT']
print('Checking LTP resolution for labels against', BASE)
for l in labels:
    try:
        r = requests.get(f"{BASE}/ltp_ws?label={l}&wait=0.3", timeout=5)
        print(l, 'ltp_ws ->', r.text)
        # If null, try /ltp fallback
        js = r.json()
        val = None
        if 'ltp' in js and js['ltp'] is not None:
            val = js['ltp']
        elif 'ltps' in js and isinstance(js['ltps'], dict):
            # pick first
            for k,v in js['ltps'].items():
                val = v; break
        if val is None:
            r2 = requests.get(f"{BASE}/ltp?label={l}", timeout=5)
            print('  fallback /ltp ->', r2.text)
    except Exception as e:
        print(l, 'error ->', e)
    time.sleep(0.2)
print('done')
