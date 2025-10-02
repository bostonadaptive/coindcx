"""Quick test for /ltp/batch endpoint using Flask test client.
Adds project root to sys.path so it can import app when run from scripts/.
"""
import sys
import os
import json

# Ensure project root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

with app.test_client() as c:
    resp = c.post('/ltp/batch', json={'labels': ['BTCUSDT', 'ETHUSDT', 'NONEXISTENT']})
    print('status', resp.status_code)
    try:
        print(json.dumps(resp.get_json(), indent=2))
    except Exception:
        print(resp.data)
