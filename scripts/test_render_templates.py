# Simple in-process template render test
import importlib.util
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location('app', os.path.join(ROOT, 'app.py'))
app_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_mod)
app = getattr(app_mod, 'app')

ENDPOINTS = ['/algo_setup', '/algo_trading', '/backtester']

with app.test_client() as c:
    # emulate simple login
    with c.session_transaction() as sess:
        sess['user_id'] = 1
    for ep in ENDPOINTS:
        r = c.get(ep)
        body = r.get_data(as_text=True)
        print(ep, r.status_code, 'len=', len(body))
        print(body[:400].replace('\n',' '))
        print('---')
