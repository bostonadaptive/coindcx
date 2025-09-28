# In-process smoke test using Flask test_client
import importlib.util
import os
import sys

# Load the app module by path to avoid import issues
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
APP_PATH = os.path.join(ROOT, 'app.py')
spec = importlib.util.spec_from_file_location('app', APP_PATH)
app_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_mod)
app = getattr(app_mod, 'app')

ENDPOINTS = ['/trade_history/export','/trade_history/refresh','/paper_history','/get_real_wallet','/algo_setup/signals']

with app.test_client() as c:
    for ep in ENDPOINTS:
        headers = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        try:
            r = c.get(ep, headers=headers)
            ct = r.headers.get('Content-Type')
            data = r.get_data(as_text=True)[:800].replace('\n',' ')
            print(ep, r.status_code, ct)
            print('BODY:', data)
        except Exception as e:
            print(ep, 'ERROR', e)

# Test POST to algo_setup/signals without auth to see JSON 401
with app.test_client() as c:
    headers = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json'}
    try:
        r = c.post('/algo_setup/signals', json={'ids': [1,2], 'process': True}, headers=headers)
        print('/algo_setup/signals POST', r.status_code, r.headers.get('Content-Type'))
        print('BODY:', r.get_data(as_text=True)[:800].replace('\n',' '))
    except Exception as e:
        print('/algo_setup/signals POST ERROR', e)
