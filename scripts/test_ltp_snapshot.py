import os, sys
# ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

with app.test_client() as c:
    r = c.get('/ltp_snapshot')
    print('status', r.status_code)
    print(r.get_data(as_text=True)[:1000])
